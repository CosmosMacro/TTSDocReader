from pathlib import Path
import unittest

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

    def test_synthesis_requires_explicit_consent(self):
        with self.fixture.open("rb") as book:
            response = self.client.post("/api/audiobook/synthesize", files={"file": ("book.epub", book, "application/epub+zip")})
        self.assertEqual(response.status_code, 400)
        self.assertIn("confirmation", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
