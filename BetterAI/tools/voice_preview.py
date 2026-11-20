"""Render old/new Aria delivery to WAV without opening the mic or playing audio.

    .venv/bin/python tools/voice_preview.py /tmp/aria-voice
    .venv/bin/python tools/voice_preview.py ~/.cache/aria-codex --laugh

Uses cached Kokoro assets only; writes identical lines with natural and expressive delivery.
"""
import argparse
import json
import os
from pathlib import Path
import random
import re
import sys

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("OMP_NUM_THREADS", "2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / "Engines" / ".env")

import numpy as np
import soundfile as sf
from Engines import LipSync, VoiceStyle
from Engines.voice_engine import (VoiceEngine, KOKORO_VOICE, KOKORO_SR, VOICE_LIFT,
                                  blend_voice, style_voices, polish_audio, normalize_for_tts, speech_span)

LINES = [
    "Hey, there you are. How did it go?",
    "You caught me. I was absolutely going to pick the blue one.",
    "I thought that was a pretty good plan, but honestly, your idea sounds more fun!",
    "Oh no, that sounds rough. Take your time.",
    "No way, you passed! I knew you could do it.",
]


def laugh_comparison(engine, voices, base):
    """Compare the former spoken 'Ha ha!' path with her current laugh (one short "Hah!"), using identical delivery."""
    for version in ('before', 'after'):
        chunks, segments, at = [], [], 0
        delivery = VoiceStyle.Delivery(profile='expressive', rand=random.Random(42))
        for piece in delivery.pieces('Haha! You caught me.'):
            voice = voices.get(piece.style, base)
            if version == 'before' and piece.style == 'laugh':
                audio, sr, mouth = engine._synthesize(piece.text, speed=piece.speed, voice=voice,
                                                     lift_by=piece.lift, base_lift=VOICE_LIFT)
            else:
                audio, sr, mouth = engine._synthesize_piece(piece, voice, VOICE_LIFT)
            if audio is None:
                raise RuntimeError(f'Could not synthesize {piece.text!r}')
            trimmed = speech_span(audio, sr)[0]
            audio = np.clip(polish_audio(audio, sr) * piece.gain, -1, 1)
            before = np.zeros(int(sr * piece.pause_before))
            after = np.zeros(int(sr * piece.pause_after))
            local = LipSync.shift_timeline(mouth or [], (len(before) - trimmed) / sr)
            end = (len(before) + len(audio)) / sr
            local = [[a, min(b, end), *rest] for a, b, *rest in local if a < end]
            segments.extend(LipSync.shift_timeline(local, at / sr))
            chunks.extend([before, audio, after])
            at += len(before) + len(audio) + len(after)
        yield version, np.concatenate(chunks), sr, segments


def render(directory, laugh=False):
    import torch
    from kokoro import KPipeline
    torch.set_num_threads(2)
    directory.mkdir(parents=True, exist_ok=True)
    pipeline = KPipeline(lang_code=KOKORO_VOICE.strip()[0], device="cpu", repo_id="hexgrad/Kokoro-82M")
    base = blend_voice(pipeline, KOKORO_VOICE)
    engine = VoiceEngine.__new__(VoiceEngine)
    engine._kokoro, engine._voice = pipeline, base
    engine._interrupted, engine._tts_sr = False, KOKORO_SR
    if laugh:
        voices = style_voices(pipeline, base, max_share=0.22)
        for version, audio, sr, segments in laugh_comparison(engine, voices, base):
            path = directory / f'aria-laugh-{version}.wav'
            sf.write(path, audio, sr)
            path.with_suffix('.json').write_text(json.dumps(segments))
            print(path, flush=True)
        (directory / 'aria-laugh-readme.txt').write_text(
            'Haha! You caught me.\nBefore reconstructs the former Kokoro Ha ha! readout; '
            'after uses her current laugh (one short "Hah!"). JSON contains final playback cues.\n')
        return
    for profile in ("natural", "expressive"):
        voices = style_voices(pipeline, base, max_share=0.22 if profile == "expressive" else 1.0)
        delivery = VoiceStyle.Delivery(profile=profile, rand=random.Random(42))
        chunks = []
        for line in (sentence for reply in LINES for sentence in re.split(r"(?<=[.!?])\s+", reply)):
            for piece in delivery.pieces(normalize_for_tts(line), line):
                audio, sr, _ = engine._synthesize_piece(piece, voices.get(piece.style, base), VOICE_LIFT)
                if audio is None:
                    raise RuntimeError(f"Could not synthesize {piece.text!r}")
                chunks.extend([np.zeros(int(sr * piece.pause_before)),
                               np.clip(polish_audio(audio, sr) * piece.gain, -1, 1),
                               np.zeros(int(sr * piece.pause_after))])
        path = directory / f"aria-{profile}.wav"
        sf.write(path, np.concatenate(chunks), KOKORO_SR)
        print(path, flush=True)
    (directory / "lines.txt").write_text("\n".join(LINES) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument('--laugh', action='store_true', help='Compare the old laugh readout with timed breath pulses')
    args = parser.parse_args()
    render(args.directory, laugh=args.laugh)
