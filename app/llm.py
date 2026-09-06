from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from urllib import error, parse, request

DEFAULT_INSTRUCTION = (
    "Tu prépares un texte français pour une narration audio, en mode CONSERVATEUR.\n\n"
    "Conserve intégralement le sens, les faits, les chiffres, les noms propres, les exemples, les nuances, "
    "les citations, l’ordre logique, les paragraphes et la longueur informative du texte. Ne résume jamais, "
    "ne condense jamais, n’invente aucune information et ne supprime aucun passage substantiel.\n\n"
    "Modifie uniquement les artefacts qui rendent l’écoute difficile : mots coupés par la mise en page, "
    "en-têtes ou pieds de page parasites, numéros de page isolés, espaces anormaux, références de mise en "
    "page incompréhensibles à l’oral et ponctuation manifestement incorrecte.\n\n"
    "Ne corrige pas la grammaire, le vocabulaire, le registre ou le style lorsqu’ils restent compréhensibles "
    "à l’oral. Ne développe pas les abréviations, ne modifie pas les acronymes et ne reformule pas les phrases "
    "uniquement pour les rendre plus élégantes. Une reformulation très légère n’est permise que si elle est "
    "indispensable à la compréhension audio, sans changer le sens ni le niveau de précision.\n\n"
    "N’affiche jamais ton raisonnement, ton analyse, un brouillon ou des balises <think>. Vérifie silencieusement "
    "que le texte final contient bien tous les paragraphes et informations substantiels de l’entrée.\n\n"
    "Retourne immédiatement uniquement le texte révisé, sans introduction, explication, balise Markdown, "
    "commentaire ou liste de modifications."
)
MAX_INPUT_CHARS = 120_000
USER_AGENT = "TTSDocReader/1.0 (OpenAI-compatible client)"
MIN_OUTPUT_RATIO = 0.45


class LLMError(RuntimeError):
    def __init__(self, public_message: str, status_code: int = 502):
        super().__init__(public_message)
        self.public_message = public_message
        self.status_code = status_code


@dataclass(frozen=True)
class ConnectionResult:
    model_available: bool
    model_count: int


def validate_base_url(base_url: str) -> str:
    value = (base_url or "").strip().rstrip("/")
    parsed = parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LLMError("L’URL du serveur LLM est invalide.", 400)
    for suffix in ("/chat/completions", "/models"):
        if value.endswith(suffix):
            value = value[: -len(suffix)].rstrip("/")
    return value


def build_endpoint(base_url: str, path: str) -> str:
    return f"{validate_base_url(base_url)}/{path.lstrip('/')}"


def _safe_provider_detail(raw: str, api_key: str = "") -> str:
    detail = raw[:1000]
    if api_key:
        detail = detail.replace(api_key, "[REDACTED]")
    detail = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,}\"]+", r"\1[REDACTED]", detail)
    detail = re.sub(r"(?i)gsk_[A-Za-z0-9_-]+", "[REDACTED]", detail)
    return detail


def _provider_error(exc: error.HTTPError, api_key: str) -> LLMError:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except OSError:
        raw = ""
    if exc.code in {401, 403}:
        safe = _safe_provider_detail(raw, api_key)
        if exc.code == 401:
            message = "Échec d’authentification Groq (HTTP 401)."
        else:
            message = "Groq a refusé la requête (HTTP 403), probablement à cause des permissions du modèle ou du compte."
        if safe:
            message += f" Détail : {safe}"
    elif exc.code == 404:
        message = "Le modèle demandé n’est pas disponible sur ce compte Groq (HTTP 404)."
    elif exc.code == 413:
        message = "Le chapitre dépasse la taille acceptée par le modèle (HTTP 413). Découpe-le avant la révision."
    elif exc.code == 422:
        message = "Le fournisseur LLM a rejeté les paramètres de la requête (HTTP 422)."
    elif exc.code == 429:
        message = "Limite de requêtes Groq atteinte (HTTP 429). Réessaie dans quelques instants."
    else:
        safe = _safe_provider_detail(raw, api_key)
        message = f"Le fournisseur LLM a répondu HTTP {exc.code}." + (f" Détail : {safe}" if safe else "")
    return LLMError(message, exc.code)


def _read_json(url: str, api_key: str = "") -> dict:
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(url, headers=headers, method="GET")
    try:
        with request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise _provider_error(exc, api_key) from exc
    except (TimeoutError, error.URLError, OSError) as exc:
        host = parse.urlparse(url).netloc
        raise LLMError(f"Impossible de joindre {host} : erreur réseau ou TLS.", 504 if isinstance(exc, TimeoutError) else 502) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LLMError("Réponse JSON invalide du fournisseur LLM.", 502) from exc
    if not isinstance(payload, dict):
        raise LLMError("Réponse JSON invalide du fournisseur LLM.", 502)
    return payload


def list_models(base_url: str, api_key: str = "") -> list[str]:
    payload = _read_json(build_endpoint(base_url, "models"), api_key)
    items = payload.get("data")
    if not isinstance(items, list):
        raise LLMError("Réponse /models invalide du fournisseur LLM.", 502)
    return [item["id"] for item in items if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]]


def test_connection(base_url: str, model: str, api_key: str = "") -> ConnectionResult:
    models = list_models(base_url, api_key)
    return ConnectionResult(model_available=model in models, model_count=len(models))


def _remove_reasoning(text: str) -> str:
    """Return only the answer if a compatible model nevertheless emits <think>."""
    if "<think>" not in text.lower():
        return text
    match = re.search(r"<think>.*?</think>(.*)$", text, flags=re.IGNORECASE | re.DOTALL)
    if not match or not match.group(1).strip():
        raise LLMError("Le modèle a retourné uniquement son raisonnement interne, sans texte révisé.", 502)
    return match.group(1)


def propose_with_llm(text: str, instruction: str | None = None, *, base_url: str | None = None, model: str | None = None, api_key: str | None = None) -> str:
    instruction = instruction or DEFAULT_INSTRUCTION
    base_url = base_url or os.getenv("LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    model = model or os.getenv("LLM_MODEL", "local-model")
    api_key = api_key if api_key is not None else os.getenv("LLM_API_KEY", "")
    if len(text) > MAX_INPUT_CHARS:
        raise LLMError("Le chapitre est trop long pour une révision sûre. Découpe-le avant la révision.", 413)
    payload = {"model": model, "temperature": 0.2, "max_completion_tokens": 16_384, "messages": [{"role": "system", "content": instruction}, {"role": "user", "content": text}]}
    host = (parse.urlparse(validate_base_url(base_url)).hostname or "").lower()
    if host == "api.groq.com" and model in {"qwen/qwen3.6-27b", "qwen/qwen3.8-27b"}:
        payload["reasoning_effort"] = "none"
        payload["reasoning_format"] = "hidden"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(build_endpoint(base_url, "chat/completions"), data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=180) as response:
            data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise _provider_error(exc, api_key) from exc
    except (TimeoutError, error.URLError, OSError) as exc:
        host = parse.urlparse(base_url).netloc
        raise LLMError(f"Impossible de joindre {host} : erreur réseau ou TLS.", 504 if isinstance(exc, TimeoutError) else 502) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LLMError("Réponse JSON invalide du fournisseur LLM.", 502) from exc
    try:
        result = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("Réponse LLM invalide : le champ choices[0].message.content est absent.", 502) from exc
    if not isinstance(result, str) or not result.strip():
        raise LLMError("Le LLM a retourné un texte vide.", 502)
    result = _remove_reasoning(result).strip()
    if not result:
        raise LLMError("Le LLM a retourné un texte vide après suppression du raisonnement interne.", 502)
    if len(text) >= 2_000 and len(result) < len(text) * MIN_OUTPUT_RATIO:
        raise LLMError("La proposition LLM est anormalement courte et a été refusée pour éviter une perte de contenu.", 502)
    return result
