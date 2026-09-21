from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import Any, Protocol

from .books import Book
from .chunking import iter_chunks


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


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _temporary_output(path: Path) -> Path:
    """Keep the media extension so ffmpeg can infer the output container."""
    return path.with_name(f"{path.stem}.tmp{path.suffix}")


def _write_manifest(path: Path, book: Book, chapters: list[dict], fingerprint: str, status: str) -> None:
    _atomic_json(path, {"version": 2, "title": book.title, "author": book.author,
        "source": str(book.source), "status": status, "fingerprint": fingerprint, "chapters": chapters})


def _tool(name: str) -> str | None:
    configured = os.getenv(f"{name.upper()}_BIN")
    if configured:
        return configured if Path(configured).is_file() else shutil.which(configured)
    return shutil.which(name)


def _preflight_media_tools() -> tuple[str, str]:
    ffmpeg, ffprobe = _tool("ffmpeg"), _tool("ffprobe")
    missing = [name for name, value in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)) if not value]
    if missing:
        raise RuntimeError("Outil audio requis introuvable : " + ", ".join(missing) +
                           ". Installez FFmpeg ou configurez FFMPEG_BIN/FFPROBE_BIN.")
    return ffmpeg, ffprobe


def _metadata_value(value: str) -> str:
    """Escape FFmetadata control characters without allowing new fields."""
    return (value.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "")
                 .replace("#", "\\#").replace(";", "\\;").replace("=", "\\="))


def _concat_file_value(path: Path) -> str:
    # ffconcat uses POSIX separators and ends/restarts single quotes for apostrophes.
    return path.resolve().as_posix().replace("'", r"'\''")


def _chapter_duration_ms(path: Path, ffprobe: str) -> int:
    result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of",
        "default=noprint_wrappers=1:nokey=1", str(path)], text=True, capture_output=True, check=True)
    return max(1, round(float(result.stdout.strip()) * 1000))


def _concat_encoded_audio(segment_files: list[Path], output: Path, ffmpeg: str) -> None:
    """Join encoded segments through ffmpeg; never concatenate encoded bytes directly."""
    if not segment_files:
        raise ValueError("At least one audio segment is required")
    concat = output.with_suffix(output.suffix + ".concat.txt")
    tmp_output = _temporary_output(output)
    concat.write_text("\n".join(f"file '{_concat_file_value(path)}'" for path in segment_files) + "\n", encoding="utf-8")
    try:
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-c:a", "libmp3lame", "-b:a", "128k", str(tmp_output)], check=True, capture_output=True)
        tmp_output.replace(output)
    finally:
        concat.unlink(missing_ok=True)
        tmp_output.unlink(missing_ok=True)


def _assemble_m4b(book: Book, chapter_files: list[Path], output: Path) -> None:
    """Create an M4B atomically, with escaped title and chapter metadata."""
    ffmpeg, ffprobe = _preflight_media_tools()
    concat, metadata = output.with_suffix(".concat.txt"), output.with_suffix(".ffmeta")
    tmp_output = _temporary_output(output)
    current = 0
    meta_lines = [";FFMETADATA1", f"title={_metadata_value(book.title)}"]
    if book.author:
        meta_lines.append(f"artist={_metadata_value(book.author)}")
    concat_lines = []
    for chapter, path in zip(book.chapters, chapter_files):
        concat_lines.append(f"file '{_concat_file_value(path)}'")
        duration = _chapter_duration_ms(path, ffprobe)
        meta_lines.extend(["[CHAPTER]", "TIMEBASE=1/1000", f"START={current}", f"END={current + duration}",
            f"title={_metadata_value(chapter.title)}"])
        current += duration
    concat.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    metadata.write_text("\n".join(meta_lines) + "\n", encoding="utf-8")
    try:
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-i", str(metadata), "-map", "0:a", "-map_metadata", "1", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            "-f", "ipod", str(tmp_output)], check=True, capture_output=True)
        tmp_output.replace(output)
    finally:
        concat.unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)
        tmp_output.unlink(missing_ok=True)


def _provider_settings(engine: TTSProvider) -> dict[str, Any]:
    """Include explicit synthesis state but never credentials or transport-only state."""
    settings: dict[str, Any] = {}
    for name in ("model", "reference_id", "format", "sample_rate", "speed"):
        value = getattr(engine, name, None)
        if value is not None:
            settings[name] = value
    supplied = getattr(engine, "synthesis_settings", None)
    if isinstance(supplied, dict):
        settings["settings"] = supplied
    return settings


def _fingerprint(book: Book, engine: TTSProvider, voice: str | None) -> str:
    provider_type = type(engine)
    payload = {"schema": 1, "chapters": [{"index": c.index, "title": c.title, "text": c.text} for c in book.chapters],
        "voice": voice, "provider": f"{provider_type.__module__}.{provider_type.__qualname__}",
        "provider_settings": _provider_settings(engine)}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _chapter_fingerprint(chapter: Any, engine: TTSProvider, voice: str | None) -> str:
    provider_type = type(engine)
    payload = {"schema": 1, "chapter": {"index": chapter.index, "title": chapter.title, "text": chapter.text},
        "voice": voice, "provider": f"{provider_type.__module__}.{provider_type.__qualname__}",
        "provider_settings": _provider_settings(engine)}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_audio(path: Path, audio: bytes) -> None:
    """Atomically persist audio so partial writes are never reusable."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(audio)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _synthesize_chapter(engine: TTSProvider, text: str, voice: str | None, destination: Path, ffmpeg: str,
                        segment_cache: Path | None = None) -> None:
    chunks = list(iter_chunks(text, max_chars=1500))
    if not chunks:
        raise ValueError("Impossible de synthétiser un chapitre vide")
    if segment_cache is None:
        # Legacy callers keep the previous ephemeral segment behaviour.
        with TemporaryDirectory(dir=destination.parent, prefix="tts-chunks-") as temp_dir:
            _synthesize_chapter(engine, text, voice, destination, ffmpeg, Path(temp_dir))
        return
    segment_cache.mkdir(parents=True, exist_ok=True)
    segment_files = []
    for number, chunk in enumerate(chunks):
        segment = segment_cache / f"{number:04d}.mp3"
        # A non-empty complete file is the commit record for this billable call.
        if not segment.is_file() or segment.stat().st_size == 0:
            audio = engine.synthesize(chunk, voice=voice)
            if not audio:
                raise RuntimeError(f"TTS returned empty audio for chunk {number + 1}")
            _atomic_audio(segment, audio)
        segment_files.append(segment)
    if len(segment_files) == 1:
        _atomic_audio(destination, segment_files[0].read_bytes())
    else:
        _concat_encoded_audio(segment_files, destination, ffmpeg)


def build_audiobook(book: Book, output_dir: str | Path, engine: TTSProvider, voice: str | None = None) -> AudiobookResult:
    """Generate resumable chapter MP3s and a navigable M4B."""
    # Ensure no billable provider call occurs without local media prerequisites.
    ffmpeg, _ = _preflight_media_tools()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = _manifest_path(output)
    fingerprint = _fingerprint(book, engine, voice)
    existing: dict[str, dict] = {}
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if data.get("version") == 2:
                existing = {str(item.get("index")): item for item in data.get("chapters", [])}
        except (OSError, ValueError, TypeError):
            pass
    records, chapter_files = [], []
    for chapter in book.chapters:
        chapter_fingerprint = _chapter_fingerprint(chapter, engine, voice)
        filename = f"{chapter.index:03d}-{_safe_name(chapter.title, f'chapter-{chapter.index}')}-{chapter_fingerprint[:12]}.mp3"
        chapter_path = output / filename
        old = existing.get(str(chapter.index))
        if not (old and old.get("fingerprint") == chapter_fingerprint and old.get("file") == filename and chapter_path.is_file()):
            _synthesize_chapter(engine, chapter.text, voice, chapter_path, ffmpeg)
        records.append({"index": chapter.index, "title": chapter.title, "file": filename, "fingerprint": chapter_fingerprint, "status": "complete"})
        chapter_files.append(chapter_path)
        # Checkpoint each successful chapter so an interrupted run resumes without billing it again.
        _write_manifest(manifest_path, book, records, fingerprint, "in_progress")
    m4b_path = output / f"{_safe_name(book.title, 'audiobook')}.m4b"
    _assemble_m4b(book, chapter_files, m4b_path)
    # Completion is recorded only after assembly; failures retain the chapter checkpoints.
    _write_manifest(manifest_path, book, records, fingerprint, "complete")
    return AudiobookResult(chapter_files, m4b_path, manifest_path)
