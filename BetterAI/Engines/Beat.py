"""Bob to music: finds the beat of whatever the laptop plays, so her avatar can nod along to it.

The sound comes from the default speaker's monitor (`parec`, 8 kHz mono, a few seconds kept in memory only: nothing
is written down or sent anywhere). Only its loudness pulses are used: how quickly it gets louder, frame by frame
(the "onset envelope"), whose autocorrelation shows the tempo and whose comb shows where the beats fall. A talk or a
podcast has no steady pulse, so its confidence stays low and she doesn't bob (off the beat is worse than not at all).

Listening happens only while `may_listen()` says so: her avatar is on screen, she isn't speaking (her own voice would
count), no lesson is on and another app is playing a stream (`pactl list sink-inputs`, never the audio itself).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time

import numpy as np

FPS = 100                   # onset envelope frames a second
RATE = 8000
WINDOW_S = 8.0              # how much sound the tempo is found from
EVERY_S = 0.5               # how often the page is told
MIN_BPM, MAX_BPM = 60, 180
CONFIDENT = 0.35            # below this she doesn't bob
LATENCY_S = 0.08            # parec's buffering: the sound we read was played this long ago


def envelope(samples: np.ndarray, rate: int = RATE, fps: int = FPS) -> np.ndarray:
    """How sharply the sound gets louder in each frame (0 where it gets quieter)."""
    hop = rate // fps
    x = np.asarray(samples, dtype=np.float32)[: len(samples) // hop * hop].reshape(-1, hop)
    loud = np.log1p(np.sqrt((x * x).mean(axis=1)))
    rise = np.maximum(0.0, np.diff(loud, prepend=loud[:1]))
    if len(rise) > 10:                                      # only rises that stand out from their neighbourhood
        rise = np.maximum(0.0, rise - np.convolve(rise, np.ones(10) / 10, mode="same"))
    return rise


def find_beat(env: np.ndarray, fps: int = FPS):
    """(bpm, seconds from the end of `env` to the next beat, confidence 0…1). Tempi near 120 are preferred when a
    beat could be read at half or double speed."""
    e = np.asarray(env, dtype=np.float64)
    if len(e) < fps * 2 or e.max() <= 1e-9:
        return 0.0, 0.0, 0.0
    e = e - e.mean()
    r = np.correlate(e, e, mode="full")[len(e) - 1:]
    if r[0] <= 0:
        return 0.0, 0.0, 0.0
    lo, hi = int(fps * 60 / MAX_BPM), int(fps * 60 / MIN_BPM) + 1
    lags = np.arange(lo, min(hi, len(r) - 1))
    if len(lags) < 3:
        return 0.0, 0.0, 0.0
    norm = r[lags] / r[0]
    prefer = np.exp(-0.5 * np.log2((60 * fps / lags) / 120) ** 2)
    i = int(np.argmax(norm * prefer))
    lag = float(lags[i])
    if 0 < i < len(lags) - 1:                               # between whole frames (a parabola through the peak)
        a, b, c = norm[i - 1], norm[i], norm[i + 1]
        if a - 2 * b + c < 0:
            lag += 0.5 * (a - c) / (a - 2 * b + c)
    confidence = float(max(0.0, min(1.0, norm[i])))
    # where the beats fall: the offset whose comb of beats collects the most rises
    offsets = np.arange(0, lag, 0.5)
    n = len(e)
    best = max(offsets, key=lambda o: e[np.round(np.arange(o, n, lag)).astype(int).clip(0, n - 1)].sum())
    period = lag / fps
    return 60 * fps / lag, float(((best - n) / fps) % period), confidence


def others_playing(pactl_text: str, own_pids) -> bool:
    """Another app's sound stream is playing (not paused, not Aria's own voice)."""
    own = {str(p) for p in own_pids}
    for block in re.split(r"(?m)^Sink Input #", pactl_text or "")[1:]:
        if re.search(r"Corked:\s*yes", block):
            continue
        pid = re.search(r'application\.process\.id = "(\d+)"', block)
        if pid and pid.group(1) in own:
            continue
        return True
    return False


def _own_pids():
    me = os.getpid()
    pids = {me}
    try:
        out = subprocess.run(["pgrep", "-P", str(me)], capture_output=True, text=True, timeout=1).stdout
        pids |= {int(p) for p in out.split()}
    except Exception:
        pass
    return pids


def playing_now() -> bool:
    try:
        out = subprocess.run(["pactl", "list", "sink-inputs"], capture_output=True, text=True, timeout=2).stdout
    except Exception:
        return False
    return others_playing(out, _own_pids())


class BeatReader:
    """Listens to the speaker's monitor while `may_listen()` is true and tells `ui.set_beat(bpm, next_in, conf)`."""

    def __init__(self, ui, may_listen, playing=playing_now, clock=time.monotonic):
        self.ui, self.may_listen, self.playing, self.clock = ui, may_listen, playing, clock
        self._proc = None
        self._buf = np.zeros(0, np.int16)
        self._lock = threading.Lock()
        self._told = False
        self._stop = threading.Event()
        self._checked, self._others = -1e9, False

    def start(self):
        if not shutil.which("parec"):
            print("[Beat] parec not found: no bobbing to music")
            return
        threading.Thread(target=self._loop, daemon=True, name="beat").start()

    def stop(self):
        self._stop.set()
        self._close()

    def wanted(self) -> bool:
        try:
            if not self.may_listen():
                return False
        except Exception:
            return False
        now = self.clock()
        if now - self._checked >= 2.0:
            self._checked, self._others = now, bool(self.playing())
        return self._others

    def step(self):
        """One check, every EVERY_S: listen, or stop listening and tell the page once."""
        if not self.wanted():
            self._close()
            self._quiet()
            return
        self._open()
        with self._lock:
            samples = self._buf[-int(RATE * WINDOW_S):]
        if len(samples) < RATE * 3:
            return
        bpm, next_in, conf = find_beat(envelope(samples))
        if conf < CONFIDENT or not bpm:
            self._quiet()
            return
        period = 60 / bpm
        self.ui.set_beat(round(bpm, 2), round((next_in - LATENCY_S) % period, 3), round(conf, 2))
        self._told = True

    def _quiet(self):
        if self._told:
            self._told = False
            self.ui.set_beat(0, 0, 0)

    def _loop(self):
        while not self._stop.wait(EVERY_S):
            try:
                self.step()
            except Exception as e:
                print(f"[Beat] {type(e).__name__}: {e}")
                self._close()
                self._stop.wait(10)

    def _open(self):
        if self._proc and self._proc.poll() is None:
            return
        try:
            sink = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True,
                                  timeout=2).stdout.strip()
            self._proc = subprocess.Popen(
                ["parec", f"--device={sink}.monitor", "--rate", str(RATE), "--channels", "1",
                 "--format", "s16le", "--latency-msec", "50", "--client-name", "aria-beat"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"[Beat] can't listen: {e}")
            self._proc = None
            return
        self._buf = np.zeros(0, np.int16)
        threading.Thread(target=self._read, args=(self._proc,), daemon=True, name="beat-read").start()

    def _read(self, proc):
        keep = int(RATE * WINDOW_S)
        while proc.poll() is None:
            chunk = proc.stdout.read(RATE // 5 * 2)
            if not chunk:
                break
            x = np.frombuffer(chunk[: len(chunk) // 2 * 2], np.int16)
            with self._lock:
                self._buf = np.concatenate((self._buf, x))[-keep:]

    def _close(self):
        p, self._proc = self._proc, None
        if p and p.poll() is None:
            p.terminate()
        with self._lock:
            self._buf = np.zeros(0, np.int16)
