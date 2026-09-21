from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from threading import Event
import unittest
import os
from fastapi import HTTPException

from app.config import settings
from app.projects import JobRunner, ProjectStore, PublicJobError, _export_fingerprint, _fingerprint


class ProjectStoreTests(unittest.TestCase):
    def test_projects_are_persistent_and_isolated_by_uuid(self):
        with TemporaryDirectory() as temporary, patch.object(settings, "output_dir", temporary):
            source = Path(temporary) / "same-name.txt"
            source.write_text("Chapitre 1\n\nBonjour le monde, ceci est un texte suffisamment long.", encoding="utf-8")
            store = ProjectStore()
            first = store.create_from_upload(source, "same-name.txt")
            second = store.create_from_upload(source, "same-name.txt")
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(ProjectStore().get(first["id"])["source_filename"], "same-name.txt")


    def test_revision_conflict_and_locked_content_are_rejected(self):
        with TemporaryDirectory() as temporary, patch.object(settings, "output_dir", temporary):
            source = Path(temporary) / "book.txt"
            source.write_text("Contenu de test.", encoding="utf-8")
            store = ProjectStore(); project = store.create_from_upload(source, "book.txt")
            payload = {"revision": project["revision"], "chapters": project["chapters"]}
            saved = store.update(project["id"], payload)
            with self.assertRaises(RuntimeError): store.update(project["id"], payload)
            payload = {"revision": saved["revision"], "chapters": saved["chapters"]}
            payload["chapters"][0]["locked"] = True
            saved = store.update(project["id"], payload)
            payload = {"revision": saved["revision"], "chapters": saved["chapters"]}
            payload["chapters"][0]["text"] = "Modification interdite"
            with self.assertRaises(ValueError): store.update(project["id"], payload)

    def test_generation_updates_audio_without_content_revision_and_failure_keeps_good_audio(self):
        class Provider:
            def __init__(self, *args, **kwargs): pass
            def synthesize(self, text, voice=None): return b"mp3"
        with TemporaryDirectory() as temporary, patch.object(settings, "output_dir", temporary), patch.dict(os.environ, {"FISH_API_KEY": "test"}):
            source = Path(temporary) / "book.txt"; source.write_text("Contenu de test.", encoding="utf-8")
            store = ProjectStore(); project = store.create_from_upload(source, "book.txt")
            chapter = project["chapters"][0]; runner = JobRunner(store, Provider)
            runner.jobs["ok"] = {"id": "ok", "project_id": project["id"], "status": "running", "completed": 0}
            with patch("app.projects._tool", return_value="tool"), patch("app.projects._probe_audio"):
                runner._generate(project["id"], "ok", [chapter["id"]], False, False)
            saved = store.get(project["id"])
            self.assertEqual(saved["revision"], 1)
            self.assertEqual(saved["chapters"][0]["audio_status"], "ready")
            old_fingerprint = saved["chapters"][0]["_audio_fingerprint"]
            class BrokenProvider(Provider):
                def synthesize(self, text, voice=None): raise RuntimeError("secret provider response")
            runner.provider_factory = BrokenProvider; runner.jobs["bad"] = {"id": "bad", "project_id": project["id"], "status": "running", "completed": 0}
            with patch("app.projects._tool", return_value="tool"):
                with self.assertRaises(RuntimeError): runner._generate(project["id"], "bad", [chapter["id"]], True, False)
            saved = store.get(project["id"])
            self.assertEqual(saved["chapters"][0]["audio_status"], "ready")
            self.assertEqual(saved["chapters"][0]["_audio_fingerprint"], old_fingerprint)

    def test_generation_retry_reuses_completed_segments_for_matching_fingerprint(self):
        class Provider:
            calls = []
            fail_once = True
            def __init__(self, *args, **kwargs): pass
            def synthesize(self, text, voice=None):
                self.calls.append(text)
                if self.fail_once and len(self.calls) == 2: raise RuntimeError("provider failed")
                return b"mp3"
        def concat(segments, output, ffmpeg): output.write_bytes(b"joined")
        with TemporaryDirectory() as temporary, patch.object(settings, "output_dir", temporary), patch.dict(os.environ, {"FISH_API_KEY": "test"}), patch("app.projects._tool", return_value="tool"), patch("app.projects._probe_audio"), patch("app.audiobook._concat_encoded_audio", side_effect=concat):
            source = Path(temporary) / "book.txt"; source.write_text("mot " * 600, encoding="utf-8")
            store = ProjectStore(); project = store.create_from_upload(source, "book.txt"); chapter = project["chapters"][0]
            runner = JobRunner(store, Provider)
            runner.jobs["first"] = {"id": "first", "project_id": project["id"], "status": "running", "completed": 0}
            with self.assertRaises(PublicJobError): runner._generate(project, "first", [chapter["id"]], False, False)
            fingerprint = _fingerprint(chapter, project["model"], project.get("voice"))
            cache = store.directory(project["id"]) / ".tts-cache" / chapter["id"] / fingerprint
            self.assertTrue((cache / "0000.mp3").is_file())
            # Model, voice, and text each produce an isolated cache namespace.
            Provider.fail_once = False
            variants = []
            for field, value in (("model", "another-model"), ("voice", "another-voice"), ("text", chapter["text"] + " extra")):
                changed = __import__("copy").deepcopy(project)
                if field == "text": changed["chapters"][0][field] = value
                else: changed[field] = value
                variants.append(changed)
            for number, changed in enumerate(variants):
                changed_chapter = changed["chapters"][0]
                changed_fingerprint = _fingerprint(changed_chapter, changed["model"], changed.get("voice"))
                changed_cache = store.directory(project["id"]) / ".tts-cache" / chapter["id"] / changed_fingerprint
                self.assertNotEqual(changed_cache, cache)
                runner.jobs[f"changed-{number}"] = {"id": f"changed-{number}", "project_id": project["id"], "status": "running", "completed": 0}
                runner._generate(changed, f"changed-{number}", [chapter["id"]], True, False)
                self.assertTrue((changed_cache / "0000.mp3").is_file())
            self.assertEqual(len(Provider.calls), 8)
            self.assertTrue((cache / "0000.mp3").is_file())
            runner.jobs["retry"] = {"id": "retry", "project_id": project["id"], "status": "running", "completed": 0}
            runner._generate(project, "retry", [chapter["id"]], False, False)
            self.assertEqual(len(Provider.calls), 9)
            self.assertFalse(cache.exists())

    def test_locked_chapter_can_be_selected_and_unlocked_but_not_edited(self):
        with TemporaryDirectory() as temporary, patch.object(settings, "output_dir", temporary):
            source = Path(temporary) / "book.txt"; source.write_text("Texte.", encoding="utf-8")
            store = ProjectStore(); project = store.create_from_upload(source, "book.txt")
            chapter = project["chapters"][0]; chapter["locked"] = True
            saved = store.update(project["id"], {"revision": 1, "chapters": [chapter]})
            chapter = saved["chapters"][0]; chapter["selected"] = not chapter["selected"]; chapter["locked"] = False
            saved = store.update(project["id"], {"revision": saved["revision"], "chapters": [chapter]})
            self.assertFalse(saved["chapters"][0]["locked"])

    def test_removed_original_can_be_restored_with_audio_metadata(self):
        with TemporaryDirectory() as temporary, patch.object(settings, "output_dir", temporary):
            source = Path(temporary) / "book.txt"; source.write_text("Texte.", encoding="utf-8")
            store = ProjectStore(); project = store.create_from_upload(source, "book.txt")
            chapter = project["chapters"][0]; chapter["_audio_fingerprint"] = "old"; chapter["audio_status"] = "stale"
            store.save(project)
            removed = store.update(project["id"], {"revision": 1, "chapters": []})
            restored = store.update(project["id"], {"revision": removed["revision"], "chapters": [{
                "id": chapter["id"], "title": chapter["title"], "text": chapter["text"],
                "selected": True, "locked": False, "listened": False}]})
            self.assertEqual(restored["chapters"][0]["_audio_fingerprint"], "old")
            self.assertEqual(len(restored["history"]), 2)

    def test_export_fingerprint_covers_metadata_order_model_voice_and_audio(self):
        project = {"title": "T", "author": "A", "model": "M", "voice": None, "chapters": [
            {"id": "1", "title": "One", "text": "x", "selected": True, "_audio_fingerprint": "a"},
            {"id": "2", "title": "Two", "text": "y", "selected": True, "_audio_fingerprint": "b"}]}
        original = _export_fingerprint(project)
        for mutate in (lambda p: p.update(title="Other"), lambda p: p.update(model="Other"),
                       lambda p: p["chapters"].reverse(), lambda p: p["chapters"][0].update(_audio_fingerprint="z")):
            copy = __import__("copy").deepcopy(project); mutate(copy); self.assertNotEqual(original, _export_fingerprint(copy))

    def test_generation_uses_start_snapshot_and_marks_concurrent_edit_stale(self):
        entered, release = Event(), Event()
        class Provider:
            def __init__(self, *args, **kwargs): pass
            def synthesize(self, text, voice=None): entered.set(); release.wait(2); return b"mp3"
        with TemporaryDirectory() as temporary, patch.object(settings, "output_dir", temporary), patch.dict(os.environ, {"FISH_API_KEY": "test"}), patch("app.projects._tool", return_value="tool"), patch("app.projects._probe_audio"):
            source = Path(temporary) / "book.txt"; source.write_text("Ancien texte.", encoding="utf-8")
            store = ProjectStore(); project = store.create_from_upload(source, "book.txt"); project["chapters"][0]["selected"] = True; store.save(project); runner = JobRunner(store, Provider)
            job = runner.start(project["id"], "generate", [project["chapters"][0]["id"]])
            self.assertTrue(entered.wait(2)); fresh = store.get(project["id"]); fresh["chapters"][0]["text"] = "Nouveau texte"
            store.update(project["id"], {"revision": fresh["revision"], "chapters": fresh["chapters"]}); release.set()
            for _ in range(100):
                status = runner.get(project["id"], job["id"])["status"]
                if status in {"complete", "failed", "cancelled"}: break
                __import__("time").sleep(.01)
            self.assertEqual(store.get(project["id"])["chapters"][0]["audio_status"], "stale")

    def test_empty_duplicate_and_unknown_targets_rejected_before_job(self):
        with TemporaryDirectory() as temporary, patch.object(settings, "output_dir", temporary):
            source = Path(temporary) / "book.txt"; source.write_text("Texte.", encoding="utf-8")
            store = ProjectStore(); project = store.create_from_upload(source, "book.txt"); runner = JobRunner(store)
            chapter_id = project["chapters"][0]["id"]
            for ids in ([], [chapter_id, chapter_id], [str(__import__("uuid").uuid4())], ["BAD"]):
                with self.assertRaises(ValueError): runner.start(project["id"], "generate", ids)
            self.assertFalse(runner.jobs)

    def test_restart_marks_active_job_failed_and_sanitizes_unknown_worker_error(self):
        with TemporaryDirectory() as temporary, patch.object(settings, "output_dir", temporary):
            source = Path(temporary) / "book.txt"; source.write_text("Texte.", encoding="utf-8")
            store = ProjectStore(); project = store.create_from_upload(source, "book.txt"); runner = JobRunner(store)
            job_id = str(__import__("uuid").uuid4()); runner.jobs[job_id] = {"id": job_id, "project_id": project["id"], "status": "running", "created_at": "x"}; runner._persist()
            recovered = JobRunner(store); self.assertEqual(recovered.jobs[job_id]["status"], "failed")
            recovered.jobs[job_id]["status"] = "queued"
            with patch.object(recovered, "_generate", side_effect=RuntimeError("secret-token")):
                recovered._run(project, job_id, "generate", None, False, False)
            self.assertNotIn("secret", recovered.jobs[job_id]["error"])

    def test_cancel_after_paid_chapter_keeps_it_and_stops_before_next(self):
        entered, release = Event(), Event()
        class Provider:
            calls = []
            def __init__(self, *args, **kwargs): pass
            def synthesize(self, text, voice=None):
                self.calls.append(text); entered.set(); release.wait(2); return b"mp3"
        with TemporaryDirectory() as temporary, patch.object(settings, "output_dir", temporary), patch.dict(os.environ, {"FISH_API_KEY": "test"}), patch("app.projects._tool", return_value="tool"), patch("app.projects._probe_audio"):
            source = Path(temporary) / "book.txt"; source.write_text("Premier texte.", encoding="utf-8")
            store = ProjectStore(); project = store.create_from_upload(source, "book.txt")
            second = project["chapters"][0].copy(); second["id"] = str(__import__("uuid").uuid4()); second["title"] = "Deux"
            second["_audio_fingerprint"] = None; second["audio_status"] = "missing"; project["chapters"].append(second); project["originals"][second["id"]] = second.copy(); store.save(project)
            runner = JobRunner(store, Provider); job = runner.start(project["id"], "generate", [c["id"] for c in project["chapters"]])
            self.assertTrue(entered.wait(2)); runner.cancel(project["id"], job["id"]); release.set()
            for _ in range(100):
                value = runner.get(project["id"], job["id"])
                if value["status"] in {"complete", "failed", "cancelled"}: break
                __import__("time").sleep(.01)
            saved = store.get(project["id"])
            self.assertEqual(value["status"], "cancelled")
            self.assertEqual(value["completed"], 1)
            self.assertEqual([c["audio_status"] for c in saved["chapters"]], ["ready", "missing"])
            self.assertEqual(len(Provider.calls), 1)
            # Seeing terminal state means a retry may start immediately.
            followup = runner.start(project["id"], "generate", [second["id"]])
            runner.cancel(project["id"], followup["id"])

    def test_assembly_rejects_concurrent_mutation_and_force_regen_stales_export(self):
        class Provider:
            def __init__(self, *args, **kwargs): pass
            def synthesize(self, text, voice=None): return b"mp3"
        with TemporaryDirectory() as temporary, patch.object(settings, "output_dir", temporary), patch.dict(os.environ, {"FISH_API_KEY": "test"}), patch("app.projects._tool", return_value="tool"), patch("app.projects._probe_audio"):
            source = Path(temporary) / "book.txt"; source.write_text("Texte.", encoding="utf-8")
            store = ProjectStore(); project = store.create_from_upload(source, "book.txt")
            project["chapters"][0]["selected"] = True
            store.save(project)
            runner = JobRunner(store, Provider)
            runner.jobs["gen"] = {"id": "gen", "project_id": project["id"], "status": "running", "completed": 0}
            runner._generate(project, "gen", [project["chapters"][0]["id"]], False, False)
            ready = store.get(project["id"]); ready["_export_fingerprint"] = _export_fingerprint(ready); store.save(ready)
            old_export = ready["_export_fingerprint"]
            runner.jobs["force"] = {"id": "force", "project_id": project["id"], "status": "running", "completed": 0}
            runner._generate(ready, "force", [ready["chapters"][0]["id"]], True, False)
            self.assertNotEqual(old_export, _export_fingerprint(store.get(project["id"])))
            snapshot = store.get(project["id"]); runner.jobs["assembly"] = {"id": "assembly", "project_id": project["id"], "status": "running", "completed": 0}
            def mutate(book, files, output):
                output.write_bytes(b"m4b"); fresh = store.get(project["id"]); fresh["title"] = "Modifié"
                store.update(project["id"], {"revision": fresh["revision"], "title": fresh["title"], "chapters": fresh["chapters"]})
            with patch("app.projects._assemble_m4b", side_effect=mutate):
                with self.assertRaises(PublicJobError): runner._assemble(snapshot, "assembly")

    def test_api_allows_stale_chapter_audio_but_denies_stale_export(self):
        from app import project_api
        with TemporaryDirectory() as temporary, patch.object(settings, "output_dir", temporary):
            source = Path(temporary) / "book.txt"; source.write_text("Texte.", encoding="utf-8")
            store = ProjectStore(); project = store.create_from_upload(source, "book.txt"); chapter = project["chapters"][0]
            chapter["audio_status"] = "stale"; chapter["_audio_fingerprint"] = "old-recording"
            store.save(project); (store.directory(project["id"]) / f"{chapter['id']}.mp3").write_bytes(b"old")
            (store.directory(project["id"]) / "audiobook.m4b").write_bytes(b"old-export")
            with patch.object(project_api, "store", store):
                response = project_api.chapter_audio(project["id"], chapter["id"])
                self.assertEqual(response.media_type, "audio/mpeg")
                public = project_api._public(store.get(project["id"]))
                self.assertIn("audio_url", public["chapters"][0])
                self.assertEqual(public["export_status"], "stale")
                with self.assertRaises(HTTPException) as caught: project_api.export(project["id"])
                self.assertEqual(caught.exception.status_code, 404)

    def test_api_requires_consent_and_rejects_explicit_empty_targets(self):
        from app import project_api
        with self.assertRaises(HTTPException) as consent:
            project_api.generate(str(__import__("uuid").uuid4()), {})
        self.assertEqual(consent.exception.status_code, 400)
        with self.assertRaises(HTTPException) as empty:
            project_api.generate(str(__import__("uuid").uuid4()), {"confirm_egress": True, "chapter_ids": []})
        self.assertEqual(empty.exception.status_code, 400)

    def test_completed_audio_for_removed_chapter_is_kept_in_original_registry(self):
        entered, release = Event(), Event()
        class Provider:
            def __init__(self, *args, **kwargs): pass
            def synthesize(self, text, voice=None): entered.set(); release.wait(2); return b"mp3"
        with TemporaryDirectory() as temporary, patch.object(settings, "output_dir", temporary), patch.dict(os.environ, {"FISH_API_KEY": "test"}), patch("app.projects._tool", return_value="tool"), patch("app.projects._probe_audio"):
            source = Path(temporary) / "book.txt"; source.write_text("Texte.", encoding="utf-8")
            store = ProjectStore(); project = store.create_from_upload(source, "book.txt"); chapter = project["chapters"][0]
            runner = JobRunner(store, Provider); job = runner.start(project["id"], "generate", [chapter["id"]])
            self.assertTrue(entered.wait(2)); store.update(project["id"], {"revision": project["revision"], "chapters": []}); release.set()
            for _ in range(100):
                value = runner.get(project["id"], job["id"])
                if value["status"] in {"complete", "failed", "cancelled"}: break
                __import__("time").sleep(.01)
            saved = store.get(project["id"]); original = saved["originals"][chapter["id"]]
            self.assertEqual(value["status"], "complete")
            self.assertEqual(original["audio_status"], "ready")
            self.assertTrue(original["_audio_fingerprint"])
