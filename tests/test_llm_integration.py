import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from app import config
from app.llm import DEFAULT_INSTRUCTION, ORAL_ADAPTATION_INSTRUCTION, LLMError, build_endpoint, list_models, propose_with_llm, test_connection as llm_test_connection
from app.main import app, settings
from fastapi.testclient import TestClient


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class LlmIntegrationTests(unittest.TestCase):
    def test_settings_api_exposes_connection_controls_without_secret(self):
        from app.main import AUDIOBOOK_HTML
        self.assertIn("Tester la connexion", AUDIOBOOK_HTML)
        self.assertIn("Fournisseur", AUDIOBOOK_HTML)
        self.assertIn("Copier la proposition", AUDIOBOOK_HTML)
        self.assertIn("/api/settings/llm/test", AUDIOBOOK_HTML)
        self.assertIn("/api/settings/llm/models", AUDIOBOOK_HTML)

    def test_modern_workspace_requests_oral_adaptation(self):
        workspace = Path("app/static/workspace.js").read_text(encoding="utf-8")
        self.assertIn("Adapter à l’oral", workspace)
        self.assertIn("fd.append('mode','oral')", workspace)
        self.assertIn("Adaptation à l’oral", workspace)
        self.assertIn("Revue des modifications proposées", workspace)

    def test_old_audiobook_url_serves_updated_workspace_and_cache_busted_script(self):
        response = self.client.get("/audiobook/legacy")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Adapter à l’oral", response.text)
        self.assertIn("fd.append('mode','oral')", response.text)
        self.assertIn("Adaptation à l’oral", response.text)
        self.assertNotIn("Proposition IA", response.text)
        self.assertIn("#status.is-loading::before", response.text)
        self.assertIn("aria-busy", response.text)
        workspace = self.client.get("/audiobook")
        self.assertEqual(workspace.status_code, 200)
        self.assertIn('id="chapterList"', workspace.text)
        self.assertIn("/static/workspace.js?v=oral-adaptation-2", workspace.text)

    def test_settings_test_endpoint_returns_provider_status_without_secret(self):
        with patch("app.main.test_connection", side_effect=LLMError("Échec d’authentification Groq (HTTP 401).", 401)):
            response = self.client.post("/api/settings/llm/test", data={"base_url": "https://api.groq.com/openai/v1", "model": "model", "api_key": "gsk_[REDACTED]"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["provider_status"], 401)
        self.assertNotIn("gsk_[REDACTED]", response.text)

    def test_proposal_error_is_not_always_503(self):
        with patch("app.main.propose_with_llm", side_effect=LLMError("Limite de requêtes Groq atteinte (HTTP 429).", 429)):
            response = self.client.post("/api/audiobook/llm-propose", data={"text": "texte"})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["provider_status"], 429)

    def test_proposal_mode_defaults_to_conservative_and_accepts_oral(self):
        with patch("app.main.propose_with_llm", return_value="texte") as proposer:
            default_response = self.client.post("/api/audiobook/llm-propose", data={"text": "texte"})
            oral_response = self.client.post("/api/audiobook/llm-propose", data={"text": "texte", "mode": "oral"})
        self.assertEqual(default_response.status_code, 200)
        self.assertEqual(oral_response.status_code, 200)
        self.assertEqual(proposer.call_args_list[0].kwargs["mode"], "conservative")
        self.assertEqual(proposer.call_args_list[1].kwargs["mode"], "oral")

    def test_oral_mode_uses_safeguarded_prompt_and_default_remains_conservative(self):
        seen = []

        def fake_urlopen(req, timeout):
            seen.append(json.loads(req.data.decode("utf-8"))["messages"][0]["content"])
            return FakeResponse({"choices": [{"message": {"content": "Texte révisé."}}]})

        with patch("app.llm.request.urlopen", side_effect=fake_urlopen):
            propose_with_llm("texte", base_url="http://local/v1", model="m")
            propose_with_llm("texte", mode="oral", base_url="http://local/v1", model="m")
        self.assertEqual(seen[0], DEFAULT_INSTRUCTION)
        self.assertEqual(seen[1], ORAL_ADAPTATION_INSTRUCTION)
        for safeguard in ("vocabulaire technique ou clinique", "citations directes", "N'ajoute aucun fait", "pas un résumé"):
            self.assertIn(safeguard, ORAL_ADAPTATION_INSTRUCTION)

    def test_long_chapter_is_rejected_without_truncation(self):
        from app.llm import MAX_INPUT_CHARS
        original = "é" * (MAX_INPUT_CHARS + 1)
        with patch("app.main.propose_with_llm", side_effect=LLMError("Le chapitre est trop long pour une révision sûre.", 413)) as proposer:
            response = self.client.post("/api/audiobook/llm-propose", data={"text": original})
        self.assertEqual(response.status_code, 413)
        proposer.assert_called_once()

    def test_groq_endpoint_is_normalized(self):
        self.assertEqual(build_endpoint("https://api.groq.com/openai/v1", "chat/completions"), "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(build_endpoint("https://api.groq.com/openai/v1/", "chat/completions"), "https://api.groq.com/openai/v1/chat/completions")
        self.assertNotIn("/v1/v1/", build_endpoint("https://api.groq.com/openai/v1/", "chat/completions"))

    def test_request_is_openai_compatible_and_utf8(self):
        seen = {}

        def fake_urlopen(req, timeout):
            seen["url"] = req.full_url
            seen["headers"] = dict(req.headers)
            seen["payload"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"choices": [{"message": {"content": "Réponse française"}}]})

        with patch("app.llm.request.urlopen", side_effect=fake_urlopen):
            result = propose_with_llm("Élève déjà prêt.", base_url="https://api.groq.com/openai/v1/", model="qwen/qwen3.6-27b", api_key="gsk_[REDACTED]")
        self.assertEqual(result, "Réponse française")
        self.assertEqual(seen["url"], "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(seen["payload"]["model"], "qwen/qwen3.6-27b")
        self.assertEqual(seen["payload"]["messages"][1]["content"], "Élève déjà prêt.")
        self.assertEqual(seen["payload"]["temperature"], 0.2)
        self.assertEqual(seen["payload"]["reasoning_effort"], "none")
        self.assertEqual(seen["payload"]["reasoning_format"], "hidden")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer gsk_[REDACTED]")
        self.assertEqual(seen["headers"]["User-agent"], "TTSDocReader/1.0 (OpenAI-compatible client)")

    def test_thinking_tags_are_not_returned_as_proposal(self):
        with patch("app.llm.request.urlopen", return_value=FakeResponse({"choices": [{"message": {"content": "<think>raisonnement interne</think>Texte final."}}]})):
            self.assertEqual(propose_with_llm("texte", base_url="http://local/v1", model="m"), "Texte final.")
        with patch("app.llm.request.urlopen", return_value=FakeResponse({"choices": [{"message": {"content": "<think>raisonnement uniquement</think>"}}]})):
            with self.assertRaises(LLMError):
                propose_with_llm("texte", base_url="http://local/v1", model="m")

    def test_suspiciously_short_long_proposal_is_rejected(self):
        original = "Phrase informative. " * 150
        with patch("app.llm.request.urlopen", return_value=FakeResponse({"choices": [{"message": {"content": "Résumé."}}]})):
            with self.assertRaises(LLMError) as caught:
                propose_with_llm(original, base_url="http://local/v1", model="m")
        self.assertIn("anormalement courte", caught.exception.public_message)

    def test_missing_key_is_allowed_for_local_server(self):
        with patch("app.llm.request.urlopen", return_value=FakeResponse({"choices": [{"message": {"content": "local"}}]})) as call:
            self.assertEqual(propose_with_llm("texte", base_url="http://127.0.0.1:1234/v1", model="local-model", api_key=""), "local")
        self.assertNotIn("Authorization", call.call_args.args[0].headers)

    def test_provider_errors_are_typed_and_sanitized(self):
        for status, expected in ((401, "authentification"), (404, "modèle"), (429, "Limite de requêtes")):
            exc = HTTPError("https://api.groq.com/openai/v1/chat/completions", status, "error", {}, None)
            exc.read = lambda: b'{"error":{"message":"bad key [REDACTED]"}}'
            with patch("app.llm.request.urlopen", side_effect=exc):
                with self.assertRaises(LLMError) as caught:
                    propose_with_llm("texte", base_url="https://api.groq.com/openai/v1", model="model", api_key="gsk_[REDACTED]")
            self.assertEqual(caught.exception.status_code, status)
            self.assertIn(expected.lower(), caught.exception.public_message.lower())
            self.assertNotIn("gsk_[REDACTED]", caught.exception.public_message)

    def test_network_timeout_and_invalid_payload_are_distinct(self):
        with patch("app.llm.request.urlopen", side_effect=TimeoutError()):
            with self.assertRaises(LLMError) as caught:
                propose_with_llm("texte", base_url="http://local/v1", model="m")
        self.assertEqual(caught.exception.status_code, 504)
        with patch("app.llm.request.urlopen", return_value=FakeResponse({"not_choices": []})):
            with self.assertRaises(LLMError) as caught:
                propose_with_llm("texte", base_url="http://local/v1", model="m")
        self.assertEqual(caught.exception.status_code, 502)
        with patch("app.llm.request.urlopen", return_value=FakeResponse({"choices": [{"message": {"content": ""}}]})):
            with self.assertRaises(LLMError):
                propose_with_llm("texte", base_url="http://local/v1", model="m")

    def test_models_and_connection_validate_selected_model(self):
        with patch("app.llm.request.urlopen", return_value=FakeResponse({"data": [{"id": "model-x"}, {"id": "model-y"}]})):
            self.assertEqual(list_models("https://api.groq.com/openai/v1/", "gsk_[REDACTED]"), ["model-x", "model-y"])
            self.assertTrue(llm_test_connection("https://api.groq.com/openai/v1", "model-x", "gsk_[REDACTED]").model_available)
            self.assertFalse(llm_test_connection("https://api.groq.com/openai/v1", "missing", "gsk_[REDACTED]").model_available)

    def test_settings_persist_without_exposing_key(self):
        with TemporaryDirectory() as tmp, patch.object(settings, "output_dir", tmp), patch.object(settings, "llm_api_key", "gsk_[REDACTED]"):
            settings.llm_base_url = "http://local/v1/"
            settings.llm_model = "local-model"
            config.save_local_llm_settings()
            settings.llm_base_url = "changed"
            settings.llm_model = "changed"
            config.load_local_llm_settings()
            saved = Path(tmp, "llm_settings.json").read_text(encoding="utf-8")
            self.assertEqual(settings.llm_base_url, "http://local/v1/")
            self.assertNotIn("gsk_[REDACTED]", self.client.get("/api/settings/llm").text)
            self.assertTrue(settings.llm_api_key)

    def test_no_secret_in_settings_response_or_html(self):
        with patch.object(settings, "llm_api_key", "gsk_[REDACTED]"):
            response = self.client.get("/api/settings/llm")
            page = self.client.get("/audiobook")
        self.assertNotIn("gsk_[REDACTED]", response.text)
        self.assertNotIn("gsk_[REDACTED]", page.text)

    @property
    def client(self):
        return TestClient(app)


if __name__ == "__main__":
    unittest.main()
