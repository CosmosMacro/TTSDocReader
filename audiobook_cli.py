from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.audiobook import build_audiobook
from app.books import apply_chapter_titles, load_book
from app.fish_audio import FishAudioProvider, estimate_cost_usd


def load_chapter_titles(path: Path) -> list[str]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, list) or not all(isinstance(title, str) for title in value):
        raise ValueError("must be a JSON array of strings")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert an EPUB/PDF into chapter MP3s and an M4B audiobook")
    parser.add_argument("input", type=Path, help="DRM-free EPUB or text PDF")
    parser.add_argument("--output-dir", type=Path, help="Output directory (default: outputs/<book>)")
    parser.add_argument("--model", default=os.getenv("FISH_MODEL", "s2.1-pro-free"))
    parser.add_argument("--voice", default=os.getenv("FISH_VOICE"), help="Fish Audio reference/voice id")
    parser.add_argument("--chapters-json", type=Path, help="JSON array of corrected chapter titles")
    parser.add_argument("--inspect", action="store_true", help="List detected chapters and exit without network access")
    parser.add_argument("--yes", action="store_true", help="Confirm sending the book text to Fish Audio")
    args = parser.parse_args()

    if not args.input.is_file():
        parser.error(f"Input file not found: {args.input}")
    if args.input.suffix.lower() not in {".epub", ".pdf", ".txt", ".md"}:
        parser.error("Input must be an EPUB, PDF, TXT or Markdown file")

    book = load_book(args.input)
    if args.chapters_json:
        try:
            book = apply_chapter_titles(book, load_chapter_titles(args.chapters_json))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            parser.error(f"Invalid --chapters-json: {exc}")

    print(f"Book: {book.title}")
    print(f"Chapters: {len(book.chapters)}")
    for chapter in book.chapters:
        print(f"{chapter.index}: {chapter.title}")

    if args.inspect:
        return 0

    api_key = os.getenv("FISH_API_KEY", "")
    if not api_key:
        parser.error("Set FISH_API_KEY in the environment")
    cost = estimate_cost_usd(book.text, args.model)
    print(f"Estimated Fish Audio cost: ${cost:.4f} USD")
    print("The book text will be sent to Fish Audio.")
    if not args.yes:
        print("Aborted: add --yes to confirm.")
        return 2

    output_dir = args.output_dir or Path("outputs") / args.input.stem
    provider = FishAudioProvider(api_key, model=args.model, reference_id=args.voice)
    result = build_audiobook(book, output_dir, provider, voice=args.voice)
    print(f"Created {len(result.chapter_files)} chapter MP3 files")
    print(f"M4B: {result.m4b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
