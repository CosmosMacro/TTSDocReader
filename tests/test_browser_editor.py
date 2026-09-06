"""Browser regression coverage for the full-screen chapter editor."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import unittest

from playwright.sync_api import sync_playwright


class BrowserEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.port = probe.getsockname()[1]
        cls.server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(cls.port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            cls.server.terminate()
            raise RuntimeError("The local test server did not start")
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.terminate()
        cls.server.wait(timeout=5)

    def test_fullscreen_editor_uses_available_space_and_cleanup_is_idempotent(self):
        page = self.browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(f"http://127.0.0.1:{self.port}/audiobook")
        page.evaluate(
            """() => {
                current = {chapters: [{
                    title: 'Introduction', text: 'Mot coup-\\r\\n\\r\\né.\\r\\n\\r\\n42\\r\\n\\r\\n' + 'Texte long. '.repeat(1200),
                    selected: true, kind: 'chapter', group: 'Contenu principal', confidence: 1
                }]};
                render();
                document.getElementById('settings').hidden = false;
            }"""
        )
        page.locator('button[data-action="fullscreen"][data-i="0"]').click()
        before = page.evaluate(
            """() => {
                const chapter = document.querySelector('.editor-fullscreen');
                const preview = chapter?.querySelector('.preview');
                const body = chapter?.querySelector('.editor-body');
                const textarea = chapter?.querySelector('.edit-text');
                const rect = element => { const r = element?.getBoundingClientRect(); return r && {width:r.width,height:r.height}; };
                const style = element => { const s = getComputedStyle(element); return {display:s.display, height:s.height, minHeight:s.minHeight, gridTemplateRows:s.gridTemplateRows, alignSelf:s.alignSelf, overflow:s.overflow}; };
                const children = Array.from(preview.children).map(element => ({tag:element.tagName, className:element.className, rect:rect(element), gridRow:getComputedStyle(element).gridRow}));
                return {viewportWidth: innerWidth, viewportHeight: innerHeight, chapter: rect(chapter), preview: rect(preview), body: rect(body), textarea: rect(textarea), chapterStyle:style(chapter), previewStyle:style(preview), bodyStyle:style(body), textareaStyle:style(textarea), children, valueLength: textarea?.value.length};
            }"""
        )
        page.locator('button[data-action="clean"][data-i="0"]').click()
        page.locator('button[data-action="apply-review"][data-i="0"]').wait_for(state="visible")
        page.locator('button[data-action="apply-review"][data-i="0"]').click()
        page.locator('.edit-text[data-i="0"]').wait_for(state="visible")
        post_apply = page.evaluate(
            """() => ({
                fullscreen: !!document.querySelector('.editor-fullscreen'),
                textMatchesDom: current.chapters[0].text === document.querySelector('.edit-text')?.value
            })"""
        )
        page.locator('button[data-action="clean"][data-i="0"]').click()
        page.wait_for_function("() => current.chapters[0].review !== undefined")
        after = page.evaluate(
            """() => ({
                fullscreen: !!document.querySelector('.editor-fullscreen'),
                changes: current.chapters[0].review?.changes.length,
                reviewStartsFromCurrent: current.chapters[0].review?.original === current.chapters[0].text,
                diff: (() => { const r = document.querySelector('.inline-diff')?.getBoundingClientRect(); return r && {width:r.width,height:r.height}; })(),
                actions: (() => { const r = document.querySelector('.review-actions')?.getBoundingClientRect(); return r && {top:r.top,bottom:r.bottom}; })()
            })"""
        )
        self.assertGreater(before["textarea"]["width"], before["viewportWidth"] * 0.9)
        self.assertGreater(before["textarea"]["height"], before["viewportHeight"] * 0.55)
        self.assertTrue(post_apply["fullscreen"])
        self.assertTrue(post_apply["textMatchesDom"])
        self.assertTrue(after["fullscreen"])
        self.assertTrue(after["reviewStartsFromCurrent"])
        self.assertEqual(after["changes"], 0)
        self.assertGreater(after["diff"]["width"], before["viewportWidth"] * 0.9)
        self.assertGreater(after["diff"]["height"], before["viewportHeight"] * 0.55)
        self.assertGreaterEqual(after["actions"]["top"], 0)
        self.assertLessEqual(after["actions"]["bottom"], before["viewportHeight"])
