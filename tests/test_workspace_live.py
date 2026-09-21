"""Local browser-to-FastAPI integration, without any external provider calls."""
from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest

import httpx
from playwright.sync_api import sync_playwright, expect


class WorkspaceLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = TemporaryDirectory(prefix="workspace-live-")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.port = probe.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        environment = os.environ.copy()
        environment.update(OUTPUT_DIR=cls.temporary.name, FISH_API_KEY="", FISH_AUDIO_API_KEY="", LLM_API_KEY="")
        cls.server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(cls.port)],
            env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=.1):
                    break
            except OSError:
                time.sleep(.1)
        else:
            cls.server.terminate()
            cls.server.wait(timeout=5)
            cls.temporary.cleanup()
            raise RuntimeError("Le serveur de test ne démarre pas.")
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.terminate()
        cls.server.wait(timeout=5)
        cls.temporary.cleanup()

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1440, "height": 950})
        self.failures = []
        self.page.on("pageerror", lambda error: self.failures.append(str(error)))
        self.page.goto(self.base)
        self.page.locator("#documentFile").set_input_files({
            "name": "essai.txt", "mimeType": "text/plain",
            "buffer": "Chapitre 1 - Début\n\nBonjour le monde. Voici la première partie.\n\nChapitre 2 - Suite\n\nVoici la seconde partie du livre.".encode(),
        })
        with self.page.expect_response(lambda response: response.url == self.base + "/api/projects" and response.request.method == "POST") as imported:
            self.page.locator("#importButton").click()
        self.assertEqual(imported.value.status, 200)
        self.project_id = imported.value.json()["id"]
        expect(self.page.locator("#workspace")).to_be_visible()
        expect(self.page.locator(".edit-text")).to_be_visible()

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.failures, [], "JavaScript errors")

    def saved(self, predicate):
        deadline = time.monotonic() + 8
        with httpx.Client(base_url=self.base) as client:
            while time.monotonic() < deadline:
                project = client.get(f"/api/projects/{self.project_id}").json()
                if predicate(project):
                    return project
                self.page.wait_for_timeout(100)
        self.fail("Les modifications ne sont pas enregistrées : " + self.page.locator("#saveState").inner_text())

    def test_edit_reopen_exclusion_and_locked_selection(self):
        self.page.locator(".edit-text").fill("Texte corrigé et sauvegardé.")
        saved = self.saved(lambda p: p["chapters"][0]["text"] == "Texte corrigé et sauvegardé.")
        chapter_id = saved["chapters"][0]["id"]
        row = self.page.locator(f'.chapter-row[data-id="{chapter_id}"]')
        row.locator('input[type="checkbox"]').uncheck()
        expect(self.page.locator(".edit-text")).not_to_be_visible()
        self.saved(lambda p: not p["chapters"][0]["selected"])
        row.locator('input[type="checkbox"]').check()
        expect(self.page.locator(".edit-text")).to_be_visible()
        self.page.locator('[data-action="lock"]').click()
        self.saved(lambda p: p["chapters"][0]["locked"])
        expect(self.page.locator(".edit-text")).not_to_be_visible()
        expect(self.page.locator('[data-action="generate-chapter"]')).to_be_visible()
        row.locator('input[type="checkbox"]').uncheck()
        self.saved(lambda p: p["chapters"][0]["locked"] and not p["chapters"][0]["selected"])
        row.locator('input[type="checkbox"]').check()
        self.saved(lambda p: p["chapters"][0]["locked"] and p["chapters"][0]["selected"])
        self.page.reload()
        self.page.locator("#projectSelect").select_option(self.project_id)
        expect(self.page.locator('[data-action="unlock"]')).to_be_visible()
        self.page.locator('[data-action="unlock"]').click()
        expect(self.page.locator(".edit-text")).to_have_value("Texte corrigé et sauvegardé.")
        self.saved(lambda p: not p["chapters"][0]["locked"])

    def test_split_undo_and_merge_preserve_text(self):
        before = self.saved(lambda p: len(p["chapters"]) == 2)
        editor = self.page.locator(".edit-text")
        original = editor.input_value()
        editor.evaluate("element => { element.focus(); element.setSelectionRange(17, 17); }")
        self.page.locator('[data-action="split"]').click()
        split = self.saved(lambda p: len(p["chapters"]) == 3)
        self.assertEqual(split["chapters"][0]["text"] + split["chapters"][1]["text"], original)
        self.page.locator("#undoButton").click()
        undone = self.saved(lambda p: len(p["chapters"]) == 2)
        self.assertEqual(undone["chapters"][0]["text"], original)
        self.assertEqual(undone["chapters"][0]["original_text"], before["chapters"][0]["original_text"])
        self.page.locator(f'.chapter-row[data-id="{before["chapters"][0]["id"]}"] .chapter-name').click()
        self.page.locator('[data-action="merge"]').click()
        merged = self.saved(lambda p: len(p["chapters"]) == 1)
        self.assertIn(before["chapters"][0]["text"], merged["chapters"][0]["text"])
        self.assertIn(before["chapters"][1]["text"], merged["chapters"][0]["text"])
        self.page.locator("#undoButton").click()
        self.saved(lambda p: len(p["chapters"]) == 2)

    def test_local_cleanup_review_accepts_partial_changes(self):
        original = "Un mot coup-\n\né.\n\n42\n\nUne longue phrase qui reste inchangée."
        self.page.locator(".edit-text").fill(original)
        self.saved(lambda p: p["chapters"][0]["text"] == original)
        self.page.locator('[data-action="clean"]').click()
        expect(self.page.locator("#reviewDialog")).to_be_visible()
        changes = self.page.locator('#reviewChanges input[type="checkbox"]')
        self.assertGreater(changes.count(), 1)
        for checkbox in changes.all():
            checkbox.uncheck()
        changes.first.check()
        with self.page.expect_response(lambda response: "/api/audiobook/apply-diff" in response.url) as applied:
            self.page.locator("#applyReview").click()
        self.assertEqual(applied.value.status, 200)
        expected = applied.value.json()["text"]
        self.assertNotEqual(expected, original)
        expect(self.page.locator(".edit-text")).to_have_value(expected)
        self.saved(lambda p: p["chapters"][0]["text"] == expected)
