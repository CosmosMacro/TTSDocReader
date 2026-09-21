from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from .projects import JobRunner, ProjectStore, _export_fingerprint, _fingerprint

router = APIRouter(prefix="/api/projects", tags=["projects"])
store = ProjectStore()
jobs = JobRunner(store)

def _public(project: dict[str, Any]) -> dict[str, Any]:
    """Hide persistence-only fingerprints while keeping the documented project shape."""
    result = {key: value for key, value in project.items() if not key.startswith("_") and key != "originals"}
    result["chapters"] = []
    for chapter in project.get("chapters", []):
        value = {key: item for key, item in chapter.items() if not key.startswith("_")}
        playable = value.get("audio_status") in {"ready", "stale"} and chapter.get("_audio_fingerprint")
        if playable and (store.directory(project["id"]) / f"{value['id']}.mp3").is_file():
            value["audio_url"] = f"/api/projects/{project['id']}/audio/{value['id']}?v={project.get('audio_revision', 0)}"
        result["chapters"].append(value)
    export = store.directory(project["id"]) / "audiobook.m4b"
    result["export_status"] = "ready" if export.is_file() and project.get("_export_fingerprint") == _export_fingerprint(project) else ("stale" if export.is_file() else "missing")
    if result["export_status"] == "ready": result["export_url"] = f"/api/projects/{project['id']}/export?v={project.get('audio_revision', 0)}"
    result["latest_job"] = jobs.latest(project["id"])
    return result

def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError): return HTTPException(404, str(exc))
    if isinstance(exc, RuntimeError): return HTTPException(409, str(exc))
    if isinstance(exc, ValueError): return HTTPException(400, str(exc))
    return HTTPException(500, "Erreur interne du serveur.")

@router.get("/capabilities")
def capabilities() -> dict[str, bool]: return jobs.capabilities()

@router.get("")
def list_projects() -> dict[str, Any]: return {"projects": store.list()}

@router.post("")
async def create_project(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".epub", ".pdf", ".docx", ".txt", ".md"}: raise HTTPException(400, "Format non pris en charge (EPUB, PDF, DOCX, TXT ou MD).")
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp:
            temp.write(await file.read()); path = Path(temp.name)
        return _public(await run_in_threadpool(store.create_from_upload, path, file.filename or "document" + suffix))
    except Exception as exc: raise _error(exc)
    finally:
        if 'path' in locals(): path.unlink(missing_ok=True)

@router.get("/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    try: return _public(store.get(project_id))
    except Exception as exc: raise _error(exc)

@router.put("/{project_id}")
def update_project(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try: return _public(store.update(project_id, payload))
    except Exception as exc: raise _error(exc)

@router.post("/{project_id}/generate")
def generate(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("confirm_egress") is not True: raise HTTPException(400, "Confirmez l’envoi du texte à Fish Audio.")
    ids = payload.get("chapter_ids")
    if ids is not None and (not isinstance(ids, list) or not ids or not all(isinstance(x, str) for x in ids)): raise HTTPException(400, "chapter_ids invalide.")
    if ids is not None and len(ids) != len(set(ids)): raise HTTPException(400, "chapter_ids contient des doublons.")
    if "force" in payload and not isinstance(payload["force"], bool): raise HTTPException(400, "force invalide.")
    if "preview" in payload and not isinstance(payload["preview"], bool): raise HTTPException(400, "preview invalide.")
    try: store.get(project_id); return jobs.start(project_id, "generate", ids, bool(payload.get("force")), bool(payload.get("preview")))
    except Exception as exc: raise _error(exc)

@router.post("/{project_id}/assemble")
def assemble(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try: store.get(project_id); return jobs.start(project_id, "assemble")
    except Exception as exc: raise _error(exc)

@router.get("/{project_id}/jobs/{job_id}")
def get_job(project_id: str, job_id: str) -> dict[str, Any]:
    try: return jobs.get(project_id, job_id)
    except Exception as exc: raise _error(exc)

@router.post("/{project_id}/jobs/{job_id}/cancel")
def cancel_job(project_id: str, job_id: str) -> dict[str, Any]:
    try: return jobs.cancel(project_id, job_id)
    except Exception as exc: raise _error(exc)

def _download(project_id: str, name: str, media: str) -> FileResponse:
    try:
        path = store.directory(project_id) / name
        if not path.is_file(): raise FileNotFoundError("Fichier introuvable.")
        return FileResponse(path, media_type=media, filename=name)
    except Exception as exc: raise _error(exc)

@router.get("/{project_id}/audio/{chapter_id}")
def chapter_audio(project_id: str, chapter_id: str):
    try:
        project = store.get(project_id)
        chapter = next((c for c in project["chapters"] if c["id"] == chapter_id), None)
        if chapter is None: raise FileNotFoundError("Chapitre introuvable.")
        if chapter.get("audio_status") not in {"ready", "stale"} or not chapter.get("_audio_fingerprint"):
            raise FileNotFoundError("Aucun audio n’est disponible pour ce chapitre.")
    except Exception as exc: raise _error(exc)
    return _download(project_id, f"{chapter_id}.mp3", "audio/mpeg")

@router.get("/{project_id}/preview")
def preview(project_id: str): return _download(project_id, "preview.mp3", "audio/mpeg")

@router.get("/{project_id}/export")
def export(project_id: str):
    try:
        project = store.get(project_id)
        if project.get("_export_fingerprint") != _export_fingerprint(project):
            raise FileNotFoundError("L’export est périmé : assemblez à nouveau l’audiobook.")
    except Exception as exc: raise _error(exc)
    return _download(project_id, "audiobook.m4b", "audio/mp4")
