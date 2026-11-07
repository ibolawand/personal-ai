"""
Train the "hey Aria" wake word model (openWakeWord format) from synthetic speech. Run once (~15 min on the RTX 4070):

    .venv/bin/python tools/train_wakeword.py          # -> models/hey_aria.onnx
    .venv/bin/python tools/train_wakeword.py --eval   # only re-run the evaluation

How:
  1. Positives: Kokoro says "hey Aria" (a few spellings, for different accents) in all 28 English voices plus blends
     of two voices, at three speeds.
  2. Negatives: Kokoro saying random sentences, and near misses ("hey Maria", "area", "hey Jarvis", "Aria" on its
     own…), plus noise and silence.
  3. Every clip gets noise, a random volume and sometimes room echo; the phrase ends at a random point near the end.
  4. openWakeWord's own feature model turns audio into embeddings (16 x 96 per 1.3 s); a small network learns
     "hey Aria" vs everything else on top of them, like openWakeWord's official models. Exported to ONNX.
  5. Evaluation on voices it never trained on: how many "hey Aria"s it catches, and false triggers per hour of
     other speech. Aria additionally has Whisper confirm each detection (wakeworddetector.py), so false triggers
     here are caught there.

Training data stays in ~/.cache/aria/wakeword/ (a few hundred MB); only the model is kept in the repo.
"""

import argparse
import os
import random
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SR = 16000
CLIP_S = 2.0
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "aria" / "wakeword"
OUT = ROOT / "models" / "hey_aria.onnx"

VOICES_US = ["af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica", "af_kore", "af_nicole", "af_nova",
             "af_river", "af_sarah", "af_sky", "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam",
             "am_michael", "am_onyx", "am_puck", "am_santa"]
VOICES_GB = ["bf_alice", "bf_emma", "bf_isabella", "bf_lily", "bm_daniel", "bm_fable", "bm_george", "bm_lewis"]
HELD_OUT = {"af_nova", "am_eric", "bf_lily", "bm_lewis"}          # never trained on: the evaluation's speakers

POSITIVE_TEXTS = ["Hey Aria", "Hey Aria!", "Hey, Aria.", "Hey Aria?", "hey aria", "Hey Ahria", "Hey Arya",
                  "Hey Ariah"]
NEAR_MISSES = ["Hey Maria", "Hey Mariah", "Hey Ariana", "Hey area", "the area", "Hey Alexa", "Hey Jarvis",
               "Hey Siri", "Hey there", "Hey Ari", "Hey Aaron", "a real one", "Aria", "aria", "an aria",
               "Hey are you", "hey arrr", "hey Era", "Hey Erica", "Hey Gloria", "Hey Laura", "Korea", "Syria",
               "malaria", "Hey hey", "Hey, how are you?", "Hey Ria", "hey, area fifty one", "Bavaria",
               "cafeteria", "criteria", "bacteria", "Maria", "Hi there", "ok Google"]
FILLER = ["so", "and then", "well", "I think", "you know", "anyway", "okay", "right", "actually", "maybe"]


class Rng:
    """random.Random's api plus numpy's standard_normal, seeded."""
    def __init__(self, seed):
        self.py, self.np = random.Random(seed), np.random.default_rng(seed)

    def random(self): return self.py.random()
    def uniform(self, a, b): return self.py.uniform(a, b)
    def randint(self, a, b): return self.py.randint(a, b)
    def choice(self, s): return s[self.py.randrange(len(s))]
    def standard_normal(self, n): return self.np.standard_normal(n)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ── 1+2. speech from Kokoro ──

def kokoro_pipelines():
    from kokoro import KPipeline
    # CPU by default: next to a running Aria (chat model + Whisper) the GPU has under 1 GB left
    dev = os.environ.get("WAKE_TRAIN_DEVICE", "cpu")
    return {"a": KPipeline(lang_code="a", device=dev, repo_id="hexgrad/Kokoro-82M"),
            "b": KPipeline(lang_code="b", device=dev, repo_id="hexgrad/Kokoro-82M")}


def say(pipes, text, voice, speed):
    from scipy.signal import resample_poly
    lang = "b" if voice.split(",")[0][0] == "b" else "a"
    parts = [r.audio.numpy() for r in pipes[lang](text, voice=voice, speed=speed) if r.audio is not None]
    if not parts:
        return None
    a = resample_poly(np.concatenate(parts), 2, 3).astype(np.float32)        # 24 kHz -> 16 kHz
    nz = np.nonzero(np.abs(a) > 0.01)[0]
    return a[max(0, nz[0] - 800): nz[-1] + 1600] if len(nz) else None        # trim silence, keep a little


def random_sentence(words, rng):
    n = rng.randint(4, 14)
    s = " ".join(rng.choice(words) for _ in range(n))
    if rng.random() < 0.3:
        s = rng.choice(FILLER) + " " + s
    return s.capitalize() + rng.choice([".", ".", "?", "!"])


def generate(force=False):
    CACHE.mkdir(parents=True, exist_ok=True)
    pos_file, neg_file = CACHE / "positives.npz", CACHE / "negatives.npz"
    if pos_file.exists() and neg_file.exists() and not force:
        log("speech already generated")
        return
    rng = random.Random(7)
    pipes = kokoro_pipelines()
    voices = VOICES_US + VOICES_GB
    train_voices = [v for v in voices if v not in HELD_OUT]
    blends = set()
    while len(blends) < 40:                                        # extra speakers: two voices averaged
        a, b = rng.sample(VOICES_US, 2) if rng.random() < 0.6 else rng.sample(VOICES_GB, 2)
        if a not in HELD_OUT and b not in HELD_OUT:
            blends.add(",".join(sorted([a, b])))
    words = [w.strip() for w in open("/usr/share/dict/words") if w.strip().isalpha() and w.islower() and len(w) < 11]

    pos, pos_held = [], []
    t = time.time()
    for v in voices + sorted(blends):
        for text in POSITIVE_TEXTS:
            for speed in (0.85, 1.0, 1.2):
                a = say(pipes, text, v, speed * rng.uniform(0.95, 1.05))
                if a is not None and len(a) < SR * 1.6:
                    (pos_held if v in HELD_OUT else pos).append(a)
    log(f"positives: {len(pos)} train, {len(pos_held)} held-out ({time.time() - t:.0f}s)")

    neg, neg_held = [], []
    t = time.time()
    for v in voices + sorted(blends):
        held = v in HELD_OUT
        for text in NEAR_MISSES:
            if rng.random() < 0.5:
                a = say(pipes, text, v, rng.uniform(0.85, 1.2))
                if a is not None:
                    (neg_held if held else neg).append(a)
        for _ in range(25 if not held else 40):
            a = say(pipes, random_sentence(words, rng), v, rng.uniform(0.85, 1.2))
            if a is not None:
                (neg_held if held else neg).append(a)
    log(f"negatives: {len(neg)} train, {len(neg_held)} held-out ({time.time() - t:.0f}s)")

    np.savez_compressed(pos_file, train=np.array(pos, dtype=object), held=np.array(pos_held, dtype=object))
    np.savez_compressed(neg_file, train=np.array(neg, dtype=object), held=np.array(neg_held, dtype=object))


# ── 3. clips with noise and echo ──

def noise(n, rng):
    kind = rng.random()
    w = rng.standard_normal(n).astype(np.float32)
    if kind < 0.4:
        return w                                                   # white
    f = np.fft.rfft(w)
    shape = 1 / np.maximum(np.arange(len(f)), 1) ** (0.5 if kind < 0.8 else 1.0)   # pink / brown
    out = np.fft.irfft(f * shape, n).astype(np.float32)
    return out / (np.abs(out).max() + 1e-6)


def echo(a, rng):
    """A small synthetic room: exponentially decaying noise as impulse response."""
    length = int(SR * rng.uniform(0.05, 0.35))
    ir = rng.standard_normal(length) * np.exp(-np.linspace(0, rng.uniform(4, 9), length))
    ir[0] = 1.0
    out = np.convolve(a, ir)[:len(a)]
    return (out / (np.abs(out).max() + 1e-6) * np.abs(a).max()).astype(np.float32)


def make_clip(speech, rng, background=None, align_end=True, seconds=CLIP_S):
    n = int(SR * seconds)
    clip = np.zeros(n, np.float32)
    if background is not None and rng.random() < 0.35:              # other speech before the wake word
        b = background[: n]
        clip[: len(b)] += b * rng.uniform(0.1, 0.5)
    s = speech[-n:]
    if rng.random() < 0.3:
        s = echo(s, rng)
    if align_end:
        end = n - int(SR * rng.uniform(0.0, 0.25))
        start = max(0, end - len(s))
        clip[start:start + len(s[-(end - start):])] += s[-(end - start):]
    else:
        start = rng.randint(0, max(0, n - len(s)))
        clip[start:start + len(s)] += s[: n - start]
    level = 10 ** (rng.uniform(-35, -12) / 20)                      # noise from quiet room to noisy
    clip += noise(n, rng) * level
    clip *= 10 ** (rng.uniform(-12, 6) / 20)                        # mic volume
    return np.clip(clip, -1, 1)


def to_int16(x):
    return (np.clip(x, -1, 1) * 32767).astype(np.int16)


# ── 4. features and training ──

def features(clips):
    from openwakeword.utils import AudioFeatures
    f = AudioFeatures(inference_framework="onnx")
    return f.embed_clips(np.stack([to_int16(c) for c in clips]), batch_size=256, ncpu=os.cpu_count())


def build_dataset(split, rng, copies):
    pos = list(np.load(CACHE / "positives.npz", allow_pickle=True)[split])
    neg = list(np.load(CACHE / "negatives.npz", allow_pickle=True)[split])
    pos_clips = [make_clip(p, rng, background=rng.choice(neg)) for p in pos for _ in range(copies)]
    # negatives are 4 s long, so each gives many 16-frame windows (a 2 s clip gives exactly one)
    neg_clips = [make_clip(x, rng, align_end=rng.random() < 0.5, seconds=4.0) for x in neg
                 for _ in range(max(1, copies // 2))]
    n = int(SR * 4.0)
    neg_clips += [noise(n, rng) * 10 ** (rng.uniform(-40, -10) / 20) for _ in range(len(neg_clips) // 10)]
    log(f"{split}: {len(pos_clips)} positive and {len(neg_clips)} negative clips, computing features…")
    xp = features(pos_clips)[:, -16:, :]                            # the phrase ends in the last 16 frames
    xn_full = features(neg_clips)
    xn = np.concatenate([xn_full[:, i:i + 16, :] for i in range(0, xn_full.shape[1] - 15, 3)])
    return xp.astype(np.float32), xn.astype(np.float32)


def train():
    import torch
    from torch import nn
    r = Rng(1)

    xp, xn = build_dataset("train", r, copies=4)
    vp, vn = build_dataset("held", r, copies=2)
    log(f"train {xp.shape[0]} pos / {xn.shape[0]} neg windows; held-out {vp.shape[0]} / {vn.shape[0]}")

    dev = os.environ.get("WAKE_TRAIN_DEVICE", "cpu")       # small network; the GPU is usually full with Aria running
    model = nn.Sequential(nn.Flatten(), nn.Linear(16 * 96, 128), nn.LayerNorm(128), nn.ReLU(),
                          nn.Linear(128, 128), nn.LayerNorm(128), nn.ReLU(), nn.Linear(128, 1), nn.Sigmoid()).to(dev)
    X = torch.tensor(np.concatenate([xp, xn]), device=dev)
    Y = torch.tensor(np.concatenate([np.ones(len(xp)), np.zeros(len(xn))]), dtype=torch.float32, device=dev)
    W = torch.where(Y == 1, len(xn) / len(xp) * 0.5, 1.0)          # positives are rare: weigh them up
    VX, VY = torch.tensor(np.concatenate([vp, vn]), device=dev), np.concatenate([np.ones(len(vp)), np.zeros(len(vn))])
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-3)
    best, best_state = -1, None
    for epoch in range(40):
        model.train()
        perm = torch.randperm(len(X), device=dev)
        for i in range(0, len(X), 512):
            idx = perm[i:i + 512]
            p = model(X[idx]).squeeze(1)
            loss = (nn.functional.binary_cross_entropy(p, Y[idx], reduction="none") * W[idx]).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            s = model(VX).squeeze(1).cpu().numpy()
        recall = (s[VY == 1] > 0.5).mean()
        fp = (s[VY == 0] > 0.5).mean()
        score = recall - 20 * fp
        if score > best:
            best, best_state = score, {k: v.clone() for k, v in model.state_dict().items()}
        if epoch % 5 == 4:
            log(f"epoch {epoch + 1}: held-out recall {recall:.3f}, false positives {fp:.4f} of windows")
    model.load_state_dict(best_state)
    model = model.cpu().eval()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(model, torch.zeros(1, 16, 96), str(OUT), input_names=["x"], output_names=["score"],
                      opset_version=13, dynamic_axes=None)
    log(f"saved {OUT} ({OUT.stat().st_size // 1024} KB)")


# ── 5. evaluation as a stream, the way Aria listens ──

def evaluate():
    from openwakeword.model import Model
    rng = Rng(3)
    pos = list(np.load(CACHE / "positives.npz", allow_pickle=True)["held"])
    neg = list(np.load(CACHE / "negatives.npz", allow_pickle=True)["held"])
    m = Model(wakeword_models=[str(OUT)], inference_framework="onnx")
    key = list(m.models.keys())[0]

    def stream_scores(audio):
        m.reset()
        a = to_int16(audio)
        return [m.predict(a[i:i + 1280])[key] for i in range(0, len(a) - 1279, 1280)]

    # recall: each held-out "hey Aria" after a second of other speech, with noise
    caught = {t: 0 for t in (0.3, 0.5, 0.7)}
    for p in pos:
        before = rng.choice(neg)[: SR]
        a = np.concatenate([before * 0.3, np.zeros(SR // 4, np.float32), p, np.zeros(SR // 2, np.float32)])
        a = a + noise(len(a), rng) * 10 ** (rng.uniform(-35, -15) / 20)
        peak = max(stream_scores(a))
        for t in caught:
            caught[t] += peak > t
    # false triggers: all held-out negative speech in a row (near misses included)
    long = np.concatenate([np.concatenate([x, np.zeros(int(SR * rng.uniform(0.2, 1.0)), np.float32)]) for x in neg])
    long = long + noise(len(long), rng) * 10 ** (-30 / 20)
    s = np.array(stream_scores(long))
    hours = len(long) / SR / 3600
    print(f"\nHeld-out voices: {len(pos)} 'hey Aria' clips, {len(long) / SR / 60:.0f} min of other speech")
    for t in caught:
        triggers = int(((s[1:] > t) & (s[:-1] <= t)).sum())
        print(f"  threshold {t}: catches {caught[t] / len(pos):.0%}, false triggers {triggers} "
              f"({triggers / hours:.1f} per hour of continuous speech)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", action="store_true", help="only evaluate models/hey_aria.onnx")
    ap.add_argument("--regenerate", action="store_true", help="make the speech again")
    args = ap.parse_args()
    if not args.eval:
        generate(force=args.regenerate)
        train()
    evaluate()
