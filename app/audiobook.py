from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Protocol

from .books import Book, Chapter


class TTSProvider(Protocol):
    def synthesize(self, text: str, voice: str | None = None) -> bytes:
        """Return encoded audio bytes for one text segment."""


@dataclass
class AudiobookResult:
    chapter_files: list[Path]
    m4b: Path
    manifest: Path


def _safe_name(value: str, fallback: str) -> str:
    value = re.sub(r"[^\w\- ]+", "", value, flags=re.UNICODE).strip()
    value = re.sub(r"\s+", "-", value)
    return (value[:80] or fallback).strip("-")


def _manifest_path(output_dir: Path) -> Path:
    return output_dir / "manifest.json"


def _write_manifest(path: Path, book: Book, chapters: list[dict], status: str) -> None:
    payload = {
        "version": 1,
        "title": book.title,
        "author": book.author,
        "source": str(book.source),
        "status": status,
        "chapters": chapters,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _chapter_duration_ms(path: Path) -> int:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        text=True,
        capture_output=True,
        check=True,
    )
    return max(1, round(float(result.stdout.strip()) * 1000))


def _assemble_m4b(book: Book, chapter_files: list[Path], output: Path) -> None:
    concat = output.with_suffix(".concat.txt")
    metadata = output.with_suffix(".ffmeta")
    current = 0
    meta_lines = [";FFMETADATA1", f"title={book.title}"]
    if book.author:
        meta_lines.append(f"artist={book.author}")
    concat_lines = []
    for chapter, path in zip(book.chapters, chapter_files):
        escaped = str(path.resolve()).replace("'", "'\\''")
        concat_lines.append(f"file '{escaped}'")
        duration = _chapter_duration_ms(path)
        meta_lines.extend([
            "[CHAPTER]", "TIMEBASE=1/1000", f"START={current}", f"END={current + duration}", f"title={chapter.title}",
        ])
        current += duration
    concat.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    metadata.write_text("\n".join(meta_lines) + "\n", encoding="utf-8")
    try:
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-i", str(metadata), "-map", "0:a", "-map_metadata", "1", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output),
        ], check=True, capture_output=True)
    finally:
        concat.unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)


def build_audiobook(book: Book, output_dir: str | Path, engine: TTSProvider, voice: str | None = None) -> AudiobookResult:
    """Generate resumable chapter MP3s and a navigable M4B."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = _manifest_path(output)
    existing: dict[str, dict] = {}
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            existing = {str(item.get("index")): item for item in data.get("chapters", [])}
        except (OSError, ValueError, TypeError):
            existing = {}

    records: list[dict] = []
    chapter_files: list[Path] = []
    for chapter in book.chapters:
        filename = f"{chapter.index:03d}-{_safe_name(chapter.title, f'chapter-{chapter.index}')}.mp3"
        chapter_path = output / filename
        old = existing.get(str(chapter.index))
        if not (old and old.get("title") == chapter.title and old.get("file") == filename and chapter_path.exists()):
            audio = engine.synthesize(chapter.text, voice=voice)
            if not audio:
                raise RuntimeError(f"TTS returned empty audio for chapter {chapter.index}")
            tmp = chapter_path.with_suffix(".mp3.tmp")
            tmp.write_bytes(audio)
            tmp.replace(chapter_path)
        record = {"index": chapter.index, "title": chapter.title, "file": filename, "status": "complete"}
        records.append(record)
        chapter_files.append(chapter_path)
        _write_manifest(manifest_path, book, records, "in_progress")

    m4b_path = output / f"{_safe_name(book.title, 'audiobook')}.m4b"
    _assemble_m4b(book, chapter_files, m4b_path)
    _write_manifest(manifest_path, book, records, "complete")
    return AudiobookResult(chapter_files, m4b_path, manifest_path)
