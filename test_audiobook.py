from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from app.audiobook import _metadata_value, build_audiobook
from app.books import Book, Chapter


class FakeEngine:
    def __init__(self, model="test-model"):
        self.calls = []
        self.model = model

    def synthesize(self, text: str, voice: str | None = None) -> bytes:
        self.calls.append((text, voice))
        return b"encoded-mp3"


def fake_assemble(book, files, output):
    output.write_bytes(b"m4b")


class AudiobookTests(unittest.TestCase):
    def _book(self, text="Text"):
        return Book("Test Book", "Author", Path("book.epub"), [Chapter("One", text, 1)])

    def _build(self, book, directory, engine, voice=None):
        with patch("app.audiobook._preflight_media_tools", return_value=("ffmpeg", "ffprobe")), \
             patch("app.audiobook._assemble_m4b", side_effect=fake_assemble):
            return build_audiobook(book, directory, engine, voice=voice)

    def test_builds_chapter_mp3s_and_m4b(self):
        with TemporaryDirectory() as tmp:
            engine = FakeEngine()
            result = self._build(self._book(), Path(tmp), engine, voice="fr_voice")
            self.assertEqual(len(engine.calls), 1)
            self.assertTrue(result.chapter_files[0].exists())
            self.assertTrue(result.m4b.exists())
            manifest = json.loads(result.manifest.read_text())
            self.assertEqual(manifest["status"], "complete")
            self.assertIn("fingerprint", manifest)

    def test_matching_fingerprint_reuses_cache(self):
        with TemporaryDirectory() as tmp:
            first, second = FakeEngine(), FakeEngine()
            self._build(self._book(), Path(tmp), first, "voice-a")
            self._build(self._book(), Path(tmp), second, "voice-a")
            self.assertEqual(len(first.calls), 1)
            self.assertEqual(second.calls, [])

    def test_text_voice_or_model_change_invalidates_cache(self):
        cases = [(self._book("Changed"), "voice-a", "test-model"),
                 (self._book(), "voice-b", "test-model"),
                 (self._book(), "voice-a", "other-model")]
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self._build(self._book(), directory, FakeEngine(), "voice-a")
            for book, voice, model in cases:
                engine = FakeEngine(model)
                self._build(book, directory, engine, voice)
                self.assertEqual(len(engine.calls), 1)

    def test_missing_media_tools_fails_before_provider_call(self):
        engine = FakeEngine()
        with TemporaryDirectory() as tmp, patch("app.audiobook._preflight_media_tools", side_effect=RuntimeError("missing ffmpeg")):
            with self.assertRaisesRegex(RuntimeError, "missing ffmpeg"):
                build_audiobook(self._book(), Path(tmp), engine)
        self.assertEqual(engine.calls, [])

    def test_interrupted_second_chapter_reuses_checkpointed_first_chapter(self):
        book = Book("Test", None, Path("book.epub"), [Chapter("One", "one", 1), Chapter("Two", "two", 2)])
        failing = FakeEngine()
        original_synthesize = failing.synthesize
        def fail_second(text, voice=None):
            if text == "two":
                raise RuntimeError("interrupted")
            return original_synthesize(text, voice)
        failing.synthesize = fail_second
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                self._build(book, directory, failing)
            retry = FakeEngine()
            self._build(book, directory, retry)
            self.assertEqual(retry.calls, [("two", None)])

    def test_long_chapter_uses_encoded_segment_concat(self):
        # Paragraph boundaries force two chunks without relying on a real encoder.
        text = ("a" * 1500) + "\n\n" + ("b" * 1500)
        with TemporaryDirectory() as tmp, \
             patch("app.audiobook._preflight_media_tools", return_value=("ffmpeg", "ffprobe")), \
             patch("app.audiobook._assemble_m4b", side_effect=fake_assemble), \
             patch("app.audiobook._concat_encoded_audio", side_effect=lambda files, out, ffmpeg: out.write_bytes(b"joined")) as concat:
            engine = FakeEngine()
            build_audiobook(self._book(text), Path(tmp), engine)
        self.assertEqual(len(engine.calls), 2)
        self.assertEqual(concat.call_count, 1)

    def test_ffmetadata_escaping_blocks_control_fields(self):
        self.assertEqual(_metadata_value("Title; artist=bad\n#comment\\x"), "Title\\; artist\\=bad\\n\\#comment\\\\x")


if __name__ == "__main__":
    unittest.main()
