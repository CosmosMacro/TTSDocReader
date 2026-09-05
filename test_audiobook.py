from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess
import unittest

from app.audiobook import build_audiobook
from app.books import Book, Chapter


class FakeEngine:
    def __init__(self):
        self.calls = []
        self.audio = self._make_mp3()

    @staticmethod
    def _make_mp3() -> bytes:
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "tone.mp3"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                "-i", "anullsrc=r=24000:cl=mono", "-t", "0.05", "-c:a", "libmp3lame",
                "-b:a", "32k", str(out), "-y",
            ], check=True)
            return out.read_bytes()

    def synthesize(self, text: str, voice: str | None = None) -> bytes:
        self.calls.append((text, voice))
        return self.audio


class AudiobookTests(unittest.TestCase):
    def test_builds_chapter_mp3s_and_m4b(self):
        book = Book("Test Book", "Author", Path("book.epub"), [
            Chapter("One", "First chapter", 1),
            Chapter("Two", "Second chapter", 2),
        ])
        with TemporaryDirectory() as tmp:
            engine = FakeEngine()
            result = build_audiobook(book, Path(tmp), engine, voice="fr_voice")
            self.assertEqual(len(engine.calls), 2)
            self.assertEqual(len(result.chapter_files), 2)
            self.assertTrue(all(p.exists() and p.suffix == ".mp3" for p in result.chapter_files))
            self.assertTrue(result.m4b.exists())
            manifest = json.loads((Path(tmp) / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["chapters"][0]["title"], "One")

    def test_resume_skips_completed_chapters(self):
        book = Book("Test Book", None, Path("book.epub"), [Chapter("One", "Text", 1)])
        with TemporaryDirectory() as tmp:
            first = FakeEngine()
            build_audiobook(book, Path(tmp), first)
            second = FakeEngine()
            build_audiobook(book, Path(tmp), second)
            self.assertEqual(len(first.calls), 1)
            self.assertEqual(len(second.calls), 0)


if __name__ == "__main__":
    unittest.main()
