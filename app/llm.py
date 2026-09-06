from __future__ import annotations

import json
import os
from urllib import error, request


DEFAULT_INSTRUCTION = (
    "Prépare ce texte pour une lecture audio naturelle. "
    "Conserve strictement les informations, les chiffres, les noms, les citations "
    "et l'ordre des idées. Ne résume pas, n'ajoute rien et ne supprime rien "
    "sauf les artefacts évidents de mise en page. Retourne uniquement le texte."
)


def propose_with_llm(
    text: str,
    instruction: str | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> str:
    """Ask a local/OpenAI-compatible chat endpoint for a reviewable proposal."""
    instruction = instruction or DEFAULT_INSTRUCTION
    base_url = (base_url or os.getenv("LLM_BASE_URL", "http://127.0.0.1:1234/v1")).rstrip("/")
    model = model or os.getenv("LLM_MODEL", "local-model")
    api_key = api_key if api_key is not None else os.getenv("LLM_API_KEY", "")
    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": text},
        ],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(f"{base_url}/chat/completions", data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=180) as response:
            data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
        except OSError:
            detail = str(exc)
        raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"LLM indisponible à {base_url} : {exc}") from exc
    try:
        result = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Réponse LLM invalide") from exc
    if not isinstance(result, str) or not result.strip():
        raise RuntimeError("Le LLM a retourné un texte vide")
    return result.strip()
