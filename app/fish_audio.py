from __future__ import annotations

import json
from urllib import error, request


PAID_PRICE_USD_PER_M_UTF8_BYTES = 15.0


def estimate_cost_usd(text: str, model: str = "s2.1-pro") -> float:
    if model.endswith("-free"):
        return 0.0
    return len(text.encode("utf-8")) / 1_000_000 * PAID_PRICE_USD_PER_M_UTF8_BYTES


class FishAudioProvider:
    """Small REST client for Fish Audio TTS, returning MP3 bytes."""

    def __init__(self, api_key: str, model: str = "s2.1-pro-free", reference_id: str | None = None, timeout: float = 120.0):
        if not api_key.strip():
            raise ValueError("Fish Audio API key is required")
        self.api_key = api_key
        self.model = model
        self.reference_id = reference_id
        self.timeout = timeout

    def synthesize(self, text: str, voice: str | None = None) -> bytes:
        if not text.strip():
            raise ValueError("Cannot synthesize empty text")
        payload: dict[str, str] = {"text": text, "format": "mp3"}
        reference_id = voice or self.reference_id
        if reference_id:
            payload["reference_id"] = reference_id
        req = request.Request(
            "https://api.fish.audio/v1/tts",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "model": self.model,
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                audio = response.read()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Fish Audio API error {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Fish Audio network error: {exc.reason}") from exc
        if not audio:
            raise RuntimeError("Fish Audio returned empty audio")
        return audio
