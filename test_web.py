from pathlib import Path
import json
import os
import subprocess
import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import AUDIOBOOK_HTML, app, settings


class AudiobookWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.fixture = Path(__file__).parent / "tests" / "fixtures" / "mvp-test-book.epub"

    def test_audiobook_page_is_available(self):
        response = self.client.get("/audiobook")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Audiobook", response.text)
        self.assertIn("Aperçu du texte", response.text)
        self.assertIn("Fusionner", response.text)
        self.assertIn("Sauvegarder le manifeste", response.text)
        self.assertIn("Nettoyer automatiquement", response.text)
        self.assertIn("Proposer avec IA", response.text)
        self.assertIn("Appliquer la sélection", response.text)
        self.assertIn("Tout accepter", response.text)
        self.assertIn("Tout refuser", response.text)
        self.assertIn("Paramètres LLM", response.text)
        self.assertIn("Plein écran", response.text)
        self.assertIn(":fullscreen", response.text)
        self.assertIn("flex:1", response.text)
        self.assertIn("min-height:24rem", response.text)
        self.assertIn("editor-fullscreen", response.text)
        self.assertIn("inline-diff", response.text)
        self.assertIn("editor-toolbar", response.text)
        self.assertIn("visibleWhitespace", response.text)

    def test_audiobook_javascript_is_valid(self):
        script = AUDIOBOOK_HTML.split("<script>", 1)[1].split("</script>", 1)[0]
        with TemporaryDirectory() as tmp:
            script_path = Path(tmp) / "audiobook.js"
            script_path.write_text(script, encoding="utf-8")
            result = subprocess.run(["node", "--check", str(script_path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cleanup_endpoint_is_local_and_deterministic(self):
        response = self.client.post("/api/audiobook/cleanup", data={"text": "mot coup-\n\né\n\n12\n\nSuite."})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cleaned"], "mot coupé\n\nSuite.")

    def test_llm_endpoint_returns_unaccepted_proposal(self):
        with patch("app.main.propose_with_llm", return_value="Texte proposé") as proposer:
            response = self.client.post("/api/audiobook/llm-propose", data={"text": "Texte original"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["proposed"], "Texte proposé")
        self.assertFalse(response.json()["accepted"])
        proposer.assert_called_once()

    def test_cleanup_preview_and_partial_diff_application(self):
        original = "Un mot coup-\n\né.\n\n12\n\nSuite."
        preview = self.client.post("/api/audiobook/cleanup-preview", data={"text": original})
        self.assertEqual(preview.status_code, 200)
        data = preview.json()
        self.assertTrue(data["changes"])
        self.assertTrue(data["segments"])
        self.assertTrue(any(segment["kind"] == "equal" for segment in data["segments"]))
        applied = self.client.post("/api/audiobook/apply-diff", data={"original": original, "proposed": data["proposed"], "accepted_ids": "[]"})
        self.assertEqual(applied.json()["text"], original)

    def test_llm_settings_do_not_return_the_secret(self):
        with patch.object(settings, "llm_api_key", "secret-value"):
            response = self.client.get("/api/settings/llm")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["api_key_configured"])
        self.assertNotIn("secret-value", response.text)

    def test_groq_key_auto_selects_groq_defaults(self):
        with TemporaryDirectory() as tmp, patch.object(settings, "output_dir", tmp), patch.object(settings, "llm_base_url", "http://127.0.0.1:1234/v1"), patch.object(settings, "llm_model", "local-model"), patch.object(settings, "llm_api_key", ""):
            response = self.client.post("/api/settings/llm", data={"base_url": "http://127.0.0.1:1234/v1", "model": "local-model", "api_key": "gsk_test_key"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["base_url"], "https://api.groq.com/openai/v1")
        self.assertEqual(response.json()["model"], "llama-3.3-70b-versatile")

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

    def test_manifest_endpoint_persists_reviewed_structure_without_api_key(self):
        structure = [{"title": "Chapitre retenu", "text": "Texte narratif", "selected": True}]
        with TemporaryDirectory() as tmp, patch.object(settings, "output_dir", tmp):
            with self.fixture.open("rb") as book:
                response = self.client.post("/api/audiobook/manifest", data={"structure_json": json.dumps(structure)}, files={"file": ("book.epub", book, "application/epub+zip")})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            manifest_path = Path(data["path"])
            self.assertTrue(manifest_path.exists())
            saved = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["units"][0]["title"], "Chapitre retenu")

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
