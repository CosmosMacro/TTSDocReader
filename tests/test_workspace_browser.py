"""Browser checks for the standalone project workspace (all APIs are mocked locally)."""
from __future__ import annotations

import json
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).parents[1] / "app"


class WorkspaceBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()

    def setUp(self):
        self.project = {
            "id": "p1", "revision": 1, "title": "Essai", "author": "Auteure", "source_filename": "essai.epub",
            "model": "m", "voice": "v", "chapters": [
                {"id": "one", "title": "Introduction", "text": "Texte initial", "original_text": "Original", "selected": True, "locked": False, "kind": "chapter", "group": "Corps", "confidence": 1, "audio_status": "ready", "audio_url": "/old.mp3"},
                {"id": "two", "title": "Annexe", "text": "Annexe", "original_text": "Annexe", "selected": False, "locked": False, "kind": "appendix", "group": "Annexes", "confidence": .8, "audio_status": "missing"},
                {"id": "three", "title": "Validé", "text": "Stable", "original_text": "Stable", "selected": True, "locked": True, "kind": "chapter", "group": "Corps", "confidence": 1, "audio_status": "ready"},
            ], "updated_at": "2026-09-06T00:00:00Z"
        }
        self.puts = []
        self.job_response = {"id": "j1", "status": "failed", "error": "Fournisseur indisponible", "completed": 0, "total": 1}
        self.pending_llm_route = None
        self.page = self.browser.new_page()
        self.page.route("**/api/projects**", self._api)
        self.page.route("**/api/audiobook/llm-propose", self._hold_llm)
        self.page.goto(f"http://127.0.0.1:{self.server.server_port}/static/workspace.html")
        self.page.wait_for_timeout(100)
        self.page.select_option("#projectSelect", "p1")
        self.page.locator("#workspace").wait_for(state="visible")

    def tearDown(self):
        self.page.close()

    def _reply(self, route, payload, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def _hold_llm(self, route):
        self.pending_llm_route = route

    def _api(self, route):
        request = route.request
        path = request.url.split("/api/projects", 1)[1]
        if request.method == "GET" and path in ("", "?"):
            return self._reply(route, {"projects": [{"id": "p1", "title": "Essai", "updated_at": "2026-09-06T00:00:00Z"}]})
        if request.method == "GET" and path == "/capabilities":
            return self._reply(route, {"fish_configured": True, "ffmpeg": True, "ffprobe": True})
        if request.method == "GET" and path == "/p1":
            return self._reply(route, self.project)
        if request.method == "PUT" and path == "/p1":
            body = json.loads(request.post_data)
            self.puts.append(body)
            body["revision"] = self.project["revision"] + 1
            self.project = body
            return self._reply(route, body)
        if request.method == "POST" and path == "/p1/generate":
            return self._reply(route, {"id": "j1", "status": "queued"})
        if request.method == "GET" and path == "/p1/jobs/j1":
            return self._reply(route, self.job_response)
        return self._reply(route, {"detail": f"route mock manquante: {request.method} {path}"}, 404)

    def test_excluded_locked_autosave_stale_audio_and_error_recovery(self):
        self.assertTrue(self.page.locator(".chapter-row.excluded").is_visible())
        self.page.locator('.chapter-row[data-id="three"] .chapter-open').click()
        self.assertTrue(self.page.locator(".locked-note").is_visible())
        self.assertFalse(self.page.locator(".edit-text").is_visible())
        self.page.locator('.chapter-row[data-id="one"] .chapter-open').click()
        editor = self.page.locator(".edit-text")
        editor.fill("Texte modifié")
        self.page.wait_for_timeout(900)
        self.assertTrue(self.puts)
        self.assertEqual(self.puts[-1]["chapters"][0]["audio_status"], "stale")
        self.page.locator("button[data-step='4']").click()
        self.page.check("#egressConsent")
        self.page.locator("#generateSelected").click()
        self.page.wait_for_timeout(1500)
        self.assertIn("Fournisseur indisponible", self.page.locator("#jobStatus").inner_text())
        self.assertTrue(self.page.locator("#generateSelected").is_enabled())
        self.page.locator("button[data-step='2']").click()
        self.page.screenshot(path=str(Path(__file__).parents[1] / "docs" / "workspace-review.png"), full_page=True)

    def test_mobile_has_no_horizontal_overflow(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 390)

    def test_audio_generation_announces_busy_state_and_clears_loading_visuals(self):
        self.job_response = {"id": "j1", "status": "running", "current_chapter_id": "one", "completed": 0, "total": 1}
        self.page.locator("button[data-step='4']").click()
        self.page.check("#egressConsent")
        self.page.locator("#generateSelected").click()
        status = self.page.locator("#jobStatus")
        status.locator("progress").wait_for(state="visible")
        self.assertEqual(status.get_attribute("aria-busy"), "true")
        self.assertTrue(status.locator(".loading-spinner").is_visible())
        self.assertTrue(status.locator("progress").is_visible())
        self.assertIn("0/1", status.inner_text())
        self.job_response = {"id": "j1", "status": "failed", "error": "Fournisseur indisponible", "completed": 0, "total": 1}
        self.page.wait_for_timeout(1300)
        self.assertEqual(status.get_attribute("aria-busy"), "false")
        self.assertEqual(status.locator(".loading-spinner").count(), 0)
        self.assertEqual(status.locator("progress").count(), 0)
        self.assertIn("Fournisseur indisponible", status.inner_text())

    def test_oral_adaptation_shows_busy_state_until_proposal_arrives(self):
        with self.page.expect_request("**/api/audiobook/llm-propose"):
            self.page.locator('[data-action="llm"]').click()
        status = self.page.locator("#chapterActivity")
        status.locator(".loading-spinner").wait_for(state="visible")
        self.assertEqual(status.get_attribute("aria-busy"), "true")
        self.assertIn("Adaptation à l’oral", status.inner_text())
        self.assertEqual(status.locator("progress").count(), 0)
        self.assertIsNotNone(self.pending_llm_route)
        self.pending_llm_route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "original": "Texte initial", "proposed": "Texte oral", "changes": [], "segments": [], "mode": "llm", "accepted": False,
        }))
        self.page.locator("#reviewDialog").wait_for(state="visible")
        self.assertEqual(status.get_attribute("aria-busy"), "false")
        self.assertEqual(status.locator(".loading-spinner").count(), 0)
