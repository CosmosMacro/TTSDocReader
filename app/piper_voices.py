from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List

from .config import settings


@dataclass
class PiperVoice:
    code: str  # e.g., fr_FR
    name: str  # e.g., siwis
    quality: str  # e.g., medium / high / low / x_low
    path: str  # absolute path to .onnx


def _parse_onnx_name(p: Path) -> PiperVoice:
    stem = p.stem  # e.g., fr_FR-siwis-medium
    parts = stem.split("-")
    code = parts[0] if len(parts) >= 1 else "unknown"
    quality = parts[-1] if len(parts) >= 2 else ""
    name = "-".join(parts[1:-1]) if len(parts) >= 3 else (parts[1] if len(parts) >= 2 else stem)
    return PiperVoice(code=code, name=name, quality=quality, path=str(p.resolve()))


def list_piper_voices() -> Dict[str, List[PiperVoice]]:
    base = Path(settings.piper_voices_dir)
    candidates: List[Path] = []
    if base.exists():
        for p in base.rglob("*.onnx"):
            try:
                if p.stat().st_size > 1_000_000:  # filter out tiny placeholder files
                    candidates.append(p)
            except Exception:
                continue

    # Also include configured single model if present and not already in list
    if settings.piper_model:
        p = Path(settings.piper_model)
        try:
            if p.exists() and p.stat().st_size > 1_000_000:
                candidates.append(p)
        except Exception:
            pass

    voices_by_lang: Dict[str, List[PiperVoice]] = {}
    seen_paths = set()
    for onnx in candidates:
        try:
            abs_path = str(onnx.resolve())
            if abs_path in seen_paths:
                continue
            seen_paths.add(abs_path)
            v = _parse_onnx_name(onnx)
            voices_by_lang.setdefault(v.code, []).append(v)
        except Exception:
            continue

    # Sort voices per language by name then quality
    for code, arr in voices_by_lang.items():
        arr.sort(key=lambda x: (x.name.lower(), x.quality.lower()))

    return voices_by_lang


def list_piper_voices_json() -> dict:
    by_lang = list_piper_voices()
    return {
        "languages": [
            {
                "code": code,
                "count": len(vs),
                "voices": [asdict(v) for v in vs],
            }
            for code, vs in sorted(by_lang.items(), key=lambda kv: kv[0])
        ]
    }
