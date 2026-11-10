"""Benchmark STT sur le laptop de démo (§3, §10) : `python demo/bench.py audio.wav [--models small base]`.

Critère : transcription d'un chunk de 3 s en moins de 3 s. Reporter les chiffres dans `demo/BENCH.md`.
"""

from __future__ import annotations

import argparse
import platform
import time
from pathlib import Path

from faster_whisper import decode_audio
from worker import SR, Transcriber

CHUNK_S = 3
SEUIL_S = 3.0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("audio", help="enregistrement d'une vraie voix (≥ 3 s)")
    p.add_argument("--models", nargs="+", default=["small", "base"])
    p.add_argument("--threads", type=int, default=0)
    p.add_argument("--reps", type=int, default=5)
    a = p.parse_args()
    audio = decode_audio(a.audio, sampling_rate=SR)
    chunk = audio[: CHUNK_S * SR]
    print(f"machine : {platform.processor() or platform.machine()} · {platform.system()}")
    for m in a.models:
        stt = Transcriber(m, a.threads, Path(__file__).resolve().parent / "models")
        lang = stt.detect(audio)
        stt.transcribe(chunk, lang, None)  # échauffement
        times = []
        for _ in range(a.reps):
            t0 = time.monotonic()
            text = stt.transcribe(chunk, lang, None)
            times.append(time.monotonic() - t0)
        med = sorted(times)[len(times) // 2]
        verdict = "OK" if med < SEUIL_S else "trop lent"
        print(f"| {m} | {med:.2f} s | {min(times):.2f} s | {max(times):.2f} s | {verdict} | {text!r} |")


if __name__ == "__main__":
    main()
