"""Persistent projects and restart-safe background audio jobs."""
from __future__ import annotations

import hashlib, json, os, shutil, subprocess, threading, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .audiobook import _assemble_m4b, _synthesize_chapter, _tool
from .books import Book, Chapter, classify_chapter, load_book
from .config import settings
from .fish_audio import FishAudioProvider

TERMINAL = {"complete", "failed", "cancelled"}

def _now(): return datetime.now(timezone.utc).isoformat()

def _uuid(value: Any, label: str) -> str:
    if not isinstance(value, str): raise ValueError(f"{label} invalide.")
    try: canonical = str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc: raise ValueError(f"{label} invalide.") from exc
    if value != canonical: raise ValueError(f"{label} invalide.")
    return value

def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def _fingerprint(chapter: dict[str, Any], model: str, voice: str | None) -> str:
    return _digest({"schema": 1, "title": chapter.get("title"), "text": chapter.get("text"), "model": model, "voice": voice})

def _export_fingerprint(project: dict[str, Any]) -> str:
    return _digest({"schema": 2, "title": project.get("title"), "author": project.get("author"),
        "model": project.get("model"), "voice": project.get("voice"), "chapters": [
        {"id": c.get("id"), "title": c.get("title"), "text": _digest(c.get("text", "")),
         "audio": c.get("_audio_fingerprint"), "audio_version": c.get("_audio_version", 0)}
        for c in project.get("chapters", []) if c.get("selected")]})

def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A unique sibling avoids collisions with a still flushing worker on Windows.
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)

def _probe_audio(path: Path, ffprobe: str) -> None:
    result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of",
        "default=noprint_wrappers=1:nokey=1", str(path)], check=True, capture_output=True, text=True)
    if float(result.stdout.strip()) <= 0: raise ValueError("Durée audio invalide.")

class ProjectStore:
    def __init__(self): self.lock = threading.RLock()
    @property
    def root(self):
        path = Path(settings.output_dir) / "projects"; path.mkdir(parents=True, exist_ok=True); return path
    def directory(self, project_id): return self.root / _uuid(project_id, "Identifiant de projet")
    def path(self, project_id): return self.directory(project_id) / "project.json"
    def get(self, project_id):
        with self.lock:
            path = self.path(project_id)
            if not path.is_file(): raise FileNotFoundError("Projet introuvable.")
            try: value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc: raise ValueError("Projet enregistré illisible.") from exc
            if not isinstance(value, dict): raise ValueError("Projet enregistré invalide.")
            return value
    def save(self, project):
        with self.lock: _atomic_json(self.path(project["id"]), project); return project
    def list(self):
        result = []
        for path in self.root.glob("*/project.json"):
            try:
                p = json.loads(path.read_text(encoding="utf-8")); result.append({key: p.get(key) for key in
                    ("id", "revision", "title", "author", "source_filename", "model", "voice", "updated_at")} |
                    {"chapter_count": len(p.get("chapters", []))})
            except (OSError, ValueError, TypeError): pass
        return sorted(result, key=lambda p: p.get("updated_at") or "", reverse=True)
    def create_from_upload(self, source, source_filename, model="s2.1-pro-free", voice=None):
        book, project_id = load_book(source), str(uuid.uuid4()); directory = self.directory(project_id)
        directory.mkdir(parents=True, exist_ok=False); safe = Path(source_filename).name
        stored = directory / ("source" + Path(safe).suffix.lower()); shutil.copyfile(source, stored)
        chapters = []
        for index, source_chapter in enumerate(book.chapters, 1):
            review = classify_chapter(source_chapter)
            chapters.append({"id": str(uuid.uuid4()), "title": source_chapter.title, "text": source_chapter.text,
                "original_text": source_chapter.text, "selected": review.selected, "locked": False,
                "kind": review.kind, "group": review.group, "confidence": review.confidence,
                "audio_status": "missing", "listened": False, "_audio_fingerprint": None, "_audio_version": 0, "_order": index})
        title = safe.rsplit(".", 1)[0] if book.title == source.stem else book.title
        project = {"id": project_id, "revision": 1, "audio_revision": 0, "title": title, "author": book.author,
            "source_filename": safe, "source": stored.name, "model": model, "voice": voice, "chapters": chapters,
            "history": [], "originals": {c["id"]: c.copy() for c in chapters}, "updated_at": _now()}
        return self.save(project)
    def update(self, project_id, payload):
        with self.lock:
            current = self.get(project_id)
            if payload.get("revision") != current.get("revision"): raise RuntimeError("Conflit de version : rechargez le projet avant d’enregistrer.")
            incoming = payload.get("chapters")
            if not isinstance(incoming, list) or not all(isinstance(c, dict) for c in incoming): raise ValueError("La liste des chapitres est requise.")
            old = {c["id"]: c for c in current["chapters"]}; originals = dict(current.get("originals") or old)
            originals.update({key: chapter.copy() for key, chapter in old.items()})
            ids = [_uuid(c.get("id"), "Identifiant de chapitre") for c in incoming]
            if len(ids) != len(set(ids)): raise ValueError("Les identifiants des chapitres doivent être uniques.")
            if any(c.get("locked") for key, c in old.items() if key not in ids): raise ValueError("Un chapitre verrouillé ne peut pas être supprimé.")
            before = [c["id"] for c in current["chapters"] if c.get("locked")]
            after = [key for key in ids if key in old and old[key].get("locked")]
            if before != after: raise ValueError("Les chapitres verrouillés ne peuvent pas être réordonnés.")
            snapshot = {"revision": current["revision"], "saved_at": current.get("updated_at"), "title": current.get("title"),
                "author": current.get("author"), "model": current.get("model"), "voice": current.get("voice"),
                "chapters": [c.copy() for c in current["chapters"]]}
            for field in ("title", "author", "model", "voice"):
                if field in payload:
                    value = payload[field]
                    if value is not None and not isinstance(value, str): raise ValueError(f"Champ {field} invalide.")
                    if field in {"title", "model"} and not str(value or "").strip(): raise ValueError(f"Champ {field} obligatoire.")
                    current[field] = value
            edited = []
            for value in incoming:
                previous = old.get(value["id"])
                chapter = (previous or originals.get(value["id"]) or {"id": value["id"], "original_text": value.get("text", ""),
                    "kind": "custom", "group": "Personnalisé", "confidence": 1.0, "audio_status": "missing",
                    "listened": False, "_audio_fingerprint": None, "_audio_version": 0}).copy()
                remains_locked = value.get("locked", previous.get("locked") if previous else False)
                if previous and previous.get("locked") and remains_locked and any(value.get(f, previous[f]) != previous[f] for f in ("title", "text")):
                    raise ValueError("Déverrouillez ce chapitre avant de modifier son contenu.")
                for field in ("title", "text", "selected", "locked", "listened"):
                    if field in value: chapter[field] = value[field]
                if not isinstance(chapter.get("title"), str) or not chapter["title"].strip() or not isinstance(chapter.get("text"), str):
                    raise ValueError("Le titre et le texte du chapitre sont obligatoires.")
                if not all(isinstance(chapter.get(f), bool) for f in ("selected", "locked", "listened")):
                    raise ValueError("Les options du chapitre doivent être booléennes.")
                if chapter.get("_audio_fingerprint") and chapter["_audio_fingerprint"] != _fingerprint(chapter, current["model"], current.get("voice")):
                    chapter["audio_status"] = "stale"
                edited.append(chapter); originals.setdefault(chapter["id"], chapter.copy())
            current["history"] = (list(current.get("history", [])) + [snapshot])[-5:]
            current["originals"], current["chapters"] = originals, edited
            current["revision"] += 1; current["updated_at"] = _now(); return self.save(current)

class PublicJobError(RuntimeError): pass

class JobRunner:
    def __init__(self, store, provider_factory: Callable[..., Any] = FishAudioProvider):
        self.store, self.provider_factory = store, provider_factory; self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="audiobook")
        self.lock = threading.RLock(); self.jobs = {}; self.cancelled = set(); self.running_projects = set(); self._recover()
    @property
    def jobs_path(self): return self.store.root / "jobs.json"
    def _persist(self):
        ordered = sorted(self.jobs.values(), key=lambda j: j.get("created_at") or "", reverse=True)
        active = [j for j in ordered if j.get("status") not in TERMINAL]
        terminal = [j for j in ordered if j.get("status") in TERMINAL][:100]
        ordered = active + terminal
        self.jobs = {j["id"]: j for j in ordered}; _atomic_json(self.jobs_path, self.jobs)
    def _recover(self):
        with self.lock:
            try:
                value = json.loads(self.jobs_path.read_text(encoding="utf-8")); self.jobs = value if isinstance(value, dict) else {}
            except (OSError, ValueError, TypeError): self.jobs = {}
            for job in self.jobs.values():
                if job.get("status") in {"queued", "running", "cancelling"}: job.update(status="failed", error="Tâche interrompue lors du redémarrage de l’application.", finished_at=_now())
            self._persist()
    def capabilities(self): return {"fish_configured": bool(os.getenv("FISH_API_KEY") or os.getenv("FISH_AUDIO_API_KEY")), "ffmpeg": bool(_tool("ffmpeg")), "ffprobe": bool(_tool("ffprobe"))}
    def latest(self, project_id):
        with self.lock:
            found = [j for j in self.jobs.values() if j.get("project_id") == project_id]
            return max(found, key=lambda j: j.get("created_at") or "").copy() if found else None
    def start(self, project_id, kind, chapter_ids=None, force=False, preview=False):
        if kind not in {"generate", "assemble"}: raise ValueError("Type de tâche invalide.")
        snapshot = self.store.get(project_id); ids = None if chapter_ids is None else list(chapter_ids)
        if kind == "generate" and ids == []: raise ValueError("Sélectionnez au moins un chapitre.")
        if ids is not None:
            ids = [_uuid(value, "Identifiant de chapitre") for value in ids]
            if len(ids) != len(set(ids)): raise ValueError("Les identifiants des chapitres doivent être uniques.")
            known = {chapter["id"] for chapter in snapshot.get("chapters", [])}
            if any(value not in known for value in ids): raise ValueError("Un chapitre demandé est introuvable.")
        with self.lock:
            if project_id in self.running_projects: raise RuntimeError("Une tâche est déjà en cours pour ce projet.")
            job_id = str(uuid.uuid4()); job = {"id": job_id, "project_id": project_id, "status": "queued", "completed": 0,
                "total": len(ids or []), "current_chapter_id": None, "error": None, "result_url": None, "kind": kind,
                "preview": bool(preview), "created_at": _now(), "finished_at": None}
            self.jobs[job_id] = job; self.running_projects.add(project_id); self._persist()
            self.executor.submit(self._run, snapshot, job_id, kind, ids, force, preview); return job.copy()
    def get(self, project_id, job_id):
        _uuid(project_id, "Identifiant de projet")
        _uuid(job_id, "Identifiant de tâche")
        with self.lock:
            if job_id not in self.jobs or self.jobs[job_id].get("project_id") != project_id: raise FileNotFoundError("Tâche introuvable.")
            return self.jobs[job_id].copy()
    def cancel(self, project_id, job_id):
        with self.lock:
            job = self.get(project_id, job_id)
            if job["status"] not in TERMINAL: self.cancelled.add(job_id); self.jobs[job_id]["status"] = "cancelling"; self._persist()
            return self.jobs[job_id].copy()
    def _cancelled(self, job_id):
        with self.lock: return job_id in self.cancelled
    def _set(self, job_id, **values):
        with self.lock: self.jobs[job_id].update(values); self._persist()
    def _finish(self, project_id, job_id, **values):
        """Publish terminal state and release the per-project slot atomically."""
        with self.lock:
            self.jobs[job_id].update(values)
            self.running_projects.discard(project_id)
            self.cancelled.discard(job_id)
            self._persist()
    def _run(self, project, job_id, kind, ids, force, preview):
        try:
            self._set(job_id, status="running")
            (self._assemble(project, job_id) if kind == "assemble" else self._generate(project, job_id, ids, force, preview))
            if self._cancelled(job_id):
                self._finish(project["id"], job_id, status="cancelled", finished_at=_now())
            else:
                self._finish(project["id"], job_id, status="complete", finished_at=_now())
        except PublicJobError as exc:
            self._finish(project["id"], job_id, status="failed", error=str(exc), finished_at=_now())
        except Exception:
            self._finish(project["id"], job_id, status="failed",
                         error="La tâche a échoué. Consultez les journaux du serveur.", finished_at=_now())
    def _generate(self, project, job_id, ids, force, preview):
        if isinstance(project, str): project = self.store.get(project)
        ffmpeg, ffprobe = _tool("ffmpeg"), _tool("ffprobe")
        if not (os.getenv("FISH_API_KEY") or os.getenv("FISH_AUDIO_API_KEY")): raise PublicJobError("La clé Fish Audio n’est pas configurée.")
        if not ffmpeg or not ffprobe: raise PublicJobError("ffmpeg et ffprobe sont requis pour générer et valider l’audio.")
        by_id = {c["id"]: c for c in project["chapters"]}
        if ids is not None and any(i not in by_id for i in ids): raise PublicJobError("Un chapitre demandé est introuvable.")
        chosen = [by_id[i] for i in ids] if ids is not None else [c for c in project["chapters"] if c.get("selected")]
        if not chosen: raise PublicJobError("Aucun chapitre sélectionné.")
        if preview: chosen = [chosen[0].copy()]; chosen[0]["text"] = chosen[0]["text"][:500]
        self._set(job_id, total=len(chosen)); provider = self.provider_factory(os.getenv("FISH_API_KEY") or os.getenv("FISH_AUDIO_API_KEY") or "", model=project["model"], reference_id=project.get("voice"))
        for position, chapter in enumerate(chosen, 1):
            if self._cancelled(job_id): return
            self._set(job_id, current_chapter_id=chapter["id"]); fingerprint = _fingerprint(chapter, project["model"], project.get("voice"))
            output = self.store.directory(project["id"]) / ("preview.mp3" if preview else f"{chapter['id']}.mp3")
            if not preview and not force and chapter.get("audio_status") == "ready" and chapter.get("_audio_fingerprint") == fingerprint and output.is_file(): self._set(job_id, completed=position); continue
            pending = output.with_name(output.stem + ".pending" + output.suffix)
            segment_cache = self.store.directory(project["id"]) / ".tts-cache" / chapter["id"] / fingerprint
            try:
                _synthesize_chapter(provider, chapter["text"], project.get("voice"), pending, ffmpeg,
                                    None if preview else segment_cache)
                _probe_audio(pending, ffprobe)
                os.replace(pending, output)
                if preview: self._set(job_id, result_url=f"/api/projects/{project['id']}/preview")
                else:
                    cache_is_current = False
                    with self.store.lock:
                        fresh = self.store.get(project["id"]); target = next((c for c in fresh["chapters"] if c["id"] == chapter["id"]), None)
                        if target:
                            target["_audio_fingerprint"] = fingerprint; target["_audio_version"] = int(target.get("_audio_version", 0)) + 1; target["audio_status"] = "ready" if _fingerprint(target, fresh["model"], fresh.get("voice")) == fingerprint else "stale"
                            target["listened"] = False
                            target.pop("error", None)
                            registry_value = target.copy()
                        else:
                            registry_value = dict(fresh.get("originals", {}).get(chapter["id"], chapter))
                            registry_value["_audio_fingerprint"] = fingerprint
                            registry_value["_audio_version"] = int(registry_value.get("_audio_version", 0)) + 1
                            registry_value["audio_status"] = "ready"
                            registry_value["listened"] = False
                            registry_value.pop("error", None)
                        fresh.setdefault("originals", {})[chapter["id"]] = registry_value
                        fresh["audio_revision"] = int(fresh.get("audio_revision", 0)) + 1
                        fresh["updated_at"] = _now()
                        self.store.save(fresh)
                        cache_is_current = target is not None and target.get("audio_status") == "ready"
                    # Do not discard a stale fingerprint cache: a user may revert
                    # their concurrent change.  Persistence must succeed first.
                    if cache_is_current:
                        shutil.rmtree(segment_cache, ignore_errors=True)
            except Exception as exc:
                pending.unlink(missing_ok=True)
                if not preview:
                    with self.store.lock:
                        fresh = self.store.get(project["id"]); target = next((c for c in fresh["chapters"] if c["id"] == chapter["id"]), None)
                        if target: target["error"] = "La génération a échoué. Réessayez ce chapitre."; fresh["updated_at"] = _now(); self.store.save(fresh)
                raise PublicJobError(f"Échec du chapitre « {chapter['title']} ».") from exc
            self._set(job_id, completed=position)
    def _assemble(self, project, job_id):
        if not (_tool("ffmpeg") and _tool("ffprobe")): raise PublicJobError("ffmpeg et ffprobe sont requis pour l’export M4B.")
        chapters = [c for c in project["chapters"] if c.get("selected")]
        if not chapters: raise PublicJobError("Aucun chapitre sélectionné.")
        if any(c.get("audio_status") != "ready" or c.get("_audio_fingerprint") != _fingerprint(c, project["model"], project.get("voice")) for c in chapters): raise PublicJobError("Certains chapitres sélectionnés n’ont pas un audio à jour.")
        files = [self.store.directory(project["id"]) / f"{c['id']}.mp3" for c in chapters]
        if not all(p.is_file() for p in files): raise PublicJobError("Un fichier audio est introuvable.")
        if self._cancelled(job_id): return
        book = Book(project["title"], project.get("author"), Path(project["source_filename"]), [Chapter(c["title"], c["text"], i + 1) for i, c in enumerate(chapters)])
        output = self.store.directory(project["id"]) / "audiobook.m4b"; pending = output.with_name("audiobook.pending.m4b")
        try:
            _assemble_m4b(book, files, pending)
            if self._cancelled(job_id): return
            with self.store.lock:
                fresh = self.store.get(project["id"])
                if _export_fingerprint(fresh) != _export_fingerprint(project):
                    raise PublicJobError("Le projet a changé pendant l’assemblage. Relancez l’export.")
                os.replace(pending, output)
                fresh["_export_fingerprint"] = _export_fingerprint(project)
                fresh["audio_revision"] = int(fresh.get("audio_revision", 0)) + 1
                fresh["updated_at"] = _now()
                self.store.save(fresh)
                self._set(job_id, result_url=f"/api/projects/{project['id']}/export")
        finally: pending.unlink(missing_ok=True)
        self._set(job_id, completed=len(chapters), total=len(chapters))
