from pathlib import Path
import os
import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class AudiobookWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.fixture = Path(__file__).parent / "tests" / "fixtures" / "mvp-test-book.epub"

    def test_audiobook_page_is_available(self):
        response = self.client.get("/audiobook")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Audiobook", response.text)

    def test_root_uses_audiobook_and_legacy_page_remains_available(self):
        root = self.client.get("/")
        legacy = self.client.get("/tts")
        self.assertEqual(root.status_code, 200)
        self.assertIn("Importe un EPUB", root.text)
        self.assertEqual(legacy.status_code, 200)
        self.assertIn("Convert PDF/DOCX/TXT/MD", legacy.text)

    def test_inspect_endpoint_returns_chapters_without_api_key(self):
        with self.fixture.open("rb") as book:
            response = self.client.post("/api/audiobook/inspect", files={"file": ("book.epub", book, "application/epub+zip")})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["title"], "Test Audiobook MVP")
        self.assertEqual(len(data["chapters"]), 4)
        self.assertIn("kind", data["chapters"][0])
        self.assertIn("confidence", data["chapters"][0])
        self.assertIn("selected", data["chapters"][0])

    def test_synthesis_requires_explicit_consent(self):
        with self.fixture.open("rb") as book:
            response = self.client.post("/api/audiobook/synthesize", files={"file": ("book.epub", book, "application/epub+zip")})
        self.assertEqual(response.status_code, 400)
        self.assertIn("confirmation", response.json()["detail"])

    def test_synthesis_persists_outputs_under_configured_directory(self):
        def fake_build(book, output_dir, provider, voice=None):
            output_dir.mkdir(parents=True, exist_ok=True)
            mp3 = output_dir / "001-Chapitre.mp3"
            m4b = output_dir / "Book.m4b"
            manifest = output_dir / "manifest.json"
            mp3.write_bytes(b"mp3")
            m4b.write_bytes(b"m4b")
            manifest.write_text("{}")
            return SimpleNamespace(chapter_files=[mp3], m4b=m4b, manifest=manifest)

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"FISH_API_KEY": "test-key"}), patch("app.main.FishAudioProvider"), patch("app.main.build_audiobook", side_effect=fake_build):
            from app.main import settings
            with patch.object(settings, "output_dir", tmp):
                with self.fixture.open("rb") as book:
                    response = self.client.post("/api/audiobook/synthesize", data={"confirm_egress": "true", "titles_json": "[]"}, files={"file": ("book.epub", book, "application/epub+zip")})
            self.assertEqual(response.status_code, 200)
            self.assertTrue((Path(tmp) / "audiobooks" / "book").exists())
            self.assertTrue((Path(tmp) / "audiobooks" / "book" / "Book.m4b").exists())


if __name__ == "__main__":
    unittest.main()
