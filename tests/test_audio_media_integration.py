"""Real FFmpeg coverage; the provider is local and never sends requests."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
import time
from unittest.mock import patch

from app.audiobook import _tool, build_audiobook
from app.books import Book, Chapter

FFMPEG, FFPROBE = _tool("ffmpeg"), _tool("ffprobe")


class LocalMp3Engine:
    model = "integration-local"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tone.mp3"
            subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=24000", "-t", "0.12", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "48k", str(path)], check=True)
            self.audio = path.read_bytes()

    def synthesize(self, text: str, voice: str | None = None) -> bytes:
        self.calls.append((text, voice))
        return self.audio


@unittest.skipUnless(FFMPEG and FFPROBE, "requires ffmpeg and ffprobe")
class AudioMediaIntegrationTests(unittest.TestCase):
    def test_project_jobs_generate_individually_and_assemble_without_synthesis(self):
        from app.config import settings
        from app.projects import JobRunner, ProjectStore

        def completed(runner, project_id, job):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                value = runner.get(project_id, job["id"])
                if value["status"] in {"complete", "failed", "cancelled"}:
                    self.assertEqual(value["status"], "complete", value.get("error"))
                    return value
                time.sleep(.03)
            self.fail("La tâche audio ne se termine pas.")

        with TemporaryDirectory() as directory, patch.object(settings, "output_dir", directory), patch.dict(os.environ, {"FISH_API_KEY": "local-test-only"}):
            source = Path(directory) / "livre.txt"
            source.write_text("Chapitre 1\n\nPremier texte.\n\nChapitre 2\n\nSecond texte.", encoding="utf-8")
            store = ProjectStore()
            project = store.create_from_upload(source, source.name)
            for chapter in project["chapters"]:
                chapter["selected"] = True
            project = store.update(project["id"], project)
            engine = LocalMp3Engine()
            runner = JobRunner(store, lambda *args, **kwargs: engine)
            try:
                for chapter in project["chapters"]:
                    completed(runner, project["id"], runner.start(project["id"], "generate", [chapter["id"]]))
                self.assertEqual(len(engine.calls), 2)
                fresh = store.get(project["id"])
                self.assertTrue(all(c["audio_status"] == "ready" for c in fresh["chapters"]))
                result = completed(runner, project["id"], runner.start(project["id"], "assemble"))
                self.assertEqual(len(engine.calls), 2, "L’assemblage ne doit pas synthétiser à nouveau")
                self.assertIn("/export", result["result_url"])
                output = store.directory(project["id"]) / "audiobook.m4b"
                self.assertEqual(len(self._chapters(output)), 2)
            finally:
                runner.executor.shutdown(wait=True)

    def _book(self, text: str = "First text") -> Book:
        return Book("Book; special = # d'Auteur", "Author; = #", Path("source.epub"), [
            Chapter("Part; special = # d'Auteur", text, 1), Chapter("Second", "Second text", 2),
        ])

    def _chapters(self, path: Path) -> list[dict]:
        result = subprocess.run([FFPROBE, "-v", "error", "-show_chapters", "-show_entries", "chapter_tags=title", "-of", "json", str(path)], text=True, capture_output=True, check=True)
        return json.loads(result.stdout)["chapters"]

    def test_real_build_metadata_cache_and_invalidation(self):
        with TemporaryDirectory(prefix="audio'book-") as directory:
            output = Path(directory)
            first = LocalMp3Engine(); result = build_audiobook(self._book(), output, first, voice="voice-a")
            self.assertEqual(len(first.calls), 2)
            self.assertEqual(self._chapters(result.m4b)[0]["tags"]["title"], "Part; special = # d'Auteur")
            reused = LocalMp3Engine(); build_audiobook(self._book(), output, reused, voice="voice-a")
            self.assertEqual(reused.calls, [])
            changed = LocalMp3Engine(); build_audiobook(self._book("Corrected text"), output, changed, voice="voice-a")
            self.assertEqual(len(changed.calls), 1)
            changed_voice = LocalMp3Engine(); build_audiobook(self._book(), output, changed_voice, voice="voice-b")
            self.assertEqual(len(changed_voice.calls), 2)

    def test_long_chapter_uses_encoded_concat_with_combined_duration(self):
        book = Book("Long", None, Path("source.txt"), [Chapter("Long", ("a" * 1500) + "\n\n" + ("b" * 1500), 1)])
        with TemporaryDirectory() as directory:
            engine = LocalMp3Engine(); result = build_audiobook(book, Path(directory), engine)
            self.assertEqual(len(engine.calls), 2)
            probe = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(result.chapter_files[0])], text=True, capture_output=True, check=True)
            self.assertGreater(float(probe.stdout.strip()), 0.18)

    def test_assembly_failure_keeps_previous_export_and_manifest(self):
        with TemporaryDirectory() as directory:
            output = Path(directory); result = build_audiobook(self._book(), output, LocalMp3Engine(), voice="voice-a")
            prior_export, prior_manifest = result.m4b.read_bytes(), result.manifest.read_bytes()
            real_run = subprocess.run
            def fail_m4b(command, *args, **kwargs):
                if "-map_metadata" in command: raise subprocess.CalledProcessError(1, command)
                return real_run(command, *args, **kwargs)
            with patch("app.audiobook.subprocess.run", side_effect=fail_m4b):
                with self.assertRaises(subprocess.CalledProcessError): build_audiobook(self._book("New text"), output, LocalMp3Engine(), voice="voice-a")
            self.assertEqual(result.m4b.read_bytes(), prior_export)
            self.assertNotEqual(result.manifest.read_bytes(), prior_manifest)
            reverted = LocalMp3Engine(); build_audiobook(self._book(), output, reverted, voice="voice-a")
            self.assertEqual(len(reverted.calls), 1)
