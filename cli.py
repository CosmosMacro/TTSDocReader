from __future__ import annotations

import argparse
from pathlib import Path

from app.pipeline import synthesize_document
from app.config import settings


def main():
    p = argparse.ArgumentParser(description="OrpheusDocReader CLI")
    p.add_argument("inputs", nargs="+", help="Files or folders to convert")
    p.add_argument("--voice", default=settings.voice, help="Voice name (optional)")
    p.add_argument("--temperature", type=float, default=settings.temperature)
    p.add_argument(
        "--repetition_penalty", type=float, default=settings.repetition_penalty
    )
    p.add_argument("--max_chars", type=int, default=1500)
    p.add_argument(
        "--audio_format",
        choices=["wav", "mp3"],
        default=settings.audio_format,
        help="Output audio format",
    )
    p.add_argument(
        "--backend",
        choices=["auto", "orpheus", "pyttsx3", "piper"],
        default=settings.tts_backend,
        help="TTS backend to use (overrides .env)",
    )
    args = p.parse_args()

    to_process: list[Path] = []
    for inp in args.inputs:
        path = Path(inp)
        if path.is_file():
            to_process.append(path)
        elif path.is_dir():
            for ext in ("*.pdf", "*.docx", "*.txt", "*.md"):
                to_process.extend(path.rglob(ext))
        else:
            print(f"[WARN] Not found: {path}")

    if not to_process:
        print("No files to process.")
        return

    for f in to_process:
        print(f"-> {f}")
        out = synthesize_document(
            f,
            voice=args.voice,
            temperature=args.temperature,
            repetition_penalty=args.repetition_penalty,
            max_chars=args.max_chars,
            backend=args.backend,
            audio_format=args.audio_format,
        )
        print(f"   Output: {out}")


if __name__ == "__main__":
    main()
