import json
import os
from dataclasses import dataclass
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()


@dataclass
class Settings:
    model_name: str = os.getenv("ORPHEUS_MODEL", "canopylabs/3b-fr-ft-research_release")
    output_dir: str = os.getenv("OUTPUT_DIR", "outputs")
    audio_format: str = os.getenv("AUDIO_FORMAT", "wav").lower()
    temperature: float = float(os.getenv("TEMPERATURE", 0.7))
    repetition_penalty: float = float(os.getenv("REPETITION_PENALTY", 1.15))
    voice: str | None = os.getenv("VOICE") or None
    tts_backend: str = os.getenv("TTS_BACKEND", "auto").lower()

    # Piper (CPU, external binary)
    # - PIPER_BIN: path or command name (e.g., "piper" or "piper.exe")
    # - PIPER_MODEL: path to a voice model .onnx (e.g., fr_FR-...-medium.onnx)
    piper_bin: str = os.getenv("PIPER_BIN", "piper.exe" if os.name == "nt" else "piper")
    piper_model: str | None = os.getenv("PIPER_MODEL") or None
    # Base directory to scan for piper voices (.onnx). Defaults to third_party/piper
    piper_voices_dir: str = os.getenv(
        "PIPER_VOICES_DIR",
        (Path(__file__).resolve().parents[1] / "third_party" / "piper").as_posix(),
    )

    # Parler TTS (prosody/style via text prompt)
    # - PARLER_MODEL: HF model id (e.g., "parler-tts/parler-tts-mini-v1")
    parler_model: str = os.getenv("PARLER_MODEL", "parler-tts/parler-tts-mini-v1")

    # Optional local/OpenAI-compatible LLM used only for review proposals.
    llm_base_url: str = os.getenv("LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    llm_model: str = os.getenv("LLM_MODEL", "local-model")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")


settings = Settings()


def _llm_settings_path() -> Path:
    return Path(settings.output_dir) / "llm_settings.json"


def load_local_llm_settings() -> None:
    try:
        data = json.loads(_llm_settings_path().read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            settings.llm_base_url = str(data.get("base_url", settings.llm_base_url))
            settings.llm_model = str(data.get("model", settings.llm_model))
            settings.llm_api_key = str(data.get("api_key", settings.llm_api_key))
    except (OSError, ValueError, TypeError):
        pass


def save_local_llm_settings() -> None:
    path = _llm_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"base_url": settings.llm_base_url, "model": settings.llm_model, "api_key": settings.llm_api_key}, ensure_ascii=False, indent=2), encoding="utf-8")


load_local_llm_settings()

# Ensure output directory exists
os.makedirs(settings.output_dir, exist_ok=True)
