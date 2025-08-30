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


settings = Settings()

# Ensure output directory exists
os.makedirs(settings.output_dir, exist_ok=True)
