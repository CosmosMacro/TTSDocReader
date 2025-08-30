from __future__ import annotations

import os
import wave
import tempfile
from pathlib import Path
from typing import Iterable, Optional

from .config import settings
import subprocess
import shutil
import subprocess

# Force CPU by default unless explicitly overridden. Some builds try CUDA by default.
os.environ.setdefault("SNAC_DEVICE", "cpu")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")

# Optional backends
IMPORT_ERROR: str | None = None

# Orpheus (GPU-recommandé)
_ORPHEUS_AVAILABLE = True
try:  # pragma: no cover
    from orpheus_tts import OrpheusModel  # type: ignore
except Exception as e:  # pragma: no cover
    _ORPHEUS_AVAILABLE = False
    IMPORT_ERROR = f"orpheus_tts unavailable: {e}"

# pyttsx3 (CPU, SAPI5 sur Windows)
_PYTTSX3_AVAILABLE = True
try:  # pragma: no cover
    import pyttsx3  # type: ignore
except Exception as e:  # pragma: no cover
    _PYTTSX3_AVAILABLE = False
    if IMPORT_ERROR is None:
        IMPORT_ERROR = f"pyttsx3 unavailable: {e}"

# Piper (CPU, external binary)
_PIPER_AVAILABLE = False
_PIPER_BIN = settings.piper_bin
_PIPER_MODEL = settings.piper_model
try:
    # Consider Piper available if the binary exists or is on PATH.
    # The model can be provided later via `--voice` or `PIPER_MODEL`.
    bin_ok = False
    if _PIPER_BIN:
        if Path(_PIPER_BIN).exists():
            bin_ok = True
        elif shutil.which(_PIPER_BIN) is not None:
            bin_ok = True
    _PIPER_AVAILABLE = bool(bin_ok)
except Exception:
    _PIPER_AVAILABLE = False

# Parler (CPU/GPU via transformers; optional)
def _parler_is_available() -> bool:
    try:  # pragma: no cover
        import parler_tts  # noqa: F401
        return True
    except Exception:
        return False


class OrpheusEngine:
    _instance: Optional["OrpheusEngine"] = None

    def __init__(self, model_name: str | None = None, force_backend: Optional[str] = None):
        self.model_name = model_name or settings.model_name
        self.model = None
        self.backend: str = "mock"  # or "orpheus" | "pyttsx3" | "piper" | "parler"
        self.desired_backend: str = (force_backend or settings.tts_backend).lower()

        desired = self.desired_backend
        # Resolution d'ordre: explicit > auto with availability
        if desired == "orpheus":
            if _ORPHEUS_AVAILABLE:
                try:
                    # Use package API signature (model_name only)
                    self.model = OrpheusModel(model_name=self.model_name)
                    self.backend = "orpheus"
                except Exception as e:  # pragma: no cover
                    IMPORT_ERROR_STR = f"orpheus_tts init failed: {e}"
                    print(f"[WARN] {IMPORT_ERROR_STR}; trying pyttsx3...")
                    if _PIPER_AVAILABLE:
                        self.backend = "piper"
                    elif _PYTTSX3_AVAILABLE:
                        self.backend = "pyttsx3"
                    else:
                        self.backend = "mock"
            else:
                print("[WARN] Orpheus backend requested but unavailable; trying pyttsx3...")
                if _PIPER_AVAILABLE:
                    self.backend = "piper"
                else:
                    self.backend = "pyttsx3" if _PYTTSX3_AVAILABLE else "mock"
        elif desired == "pyttsx3":
            self.backend = "pyttsx3" if _PYTTSX3_AVAILABLE else "mock"
        elif desired == "piper":
            self.backend = "piper" if _PIPER_AVAILABLE else ("pyttsx3" if _PYTTSX3_AVAILABLE else "mock")
        elif desired == "parler":
            # Prefer Parler; if import later fails, caller will see a clear error
            self.backend = "parler"
        else:  # auto
            if _ORPHEUS_AVAILABLE:
                try:
                    self.model = OrpheusModel(model_name=self.model_name)
                    self.backend = "orpheus"
                except Exception:  # pragma: no cover
                    # If Orpheus fails at runtime, try Parler first (better prosody), then Piper
                    if _parler_is_available():
                        self.backend = "parler"
                    elif _PIPER_AVAILABLE:
                        self.backend = "piper"
                    else:
                        self.backend = "pyttsx3" if _PYTTSX3_AVAILABLE else "mock"
            else:
                if _parler_is_available():
                    self.backend = "parler"
                elif _PIPER_AVAILABLE:
                    self.backend = "piper"
                else:
                    self.backend = "pyttsx3" if _PYTTSX3_AVAILABLE else "mock"

    @classmethod
    def instance(cls, model_name: str | None = None, force_backend: Optional[str] = None) -> "OrpheusEngine":
        desired = (force_backend or settings.tts_backend).lower()
        if cls._instance is None or getattr(cls._instance, "desired_backend", None) != desired:
            cls._instance = OrpheusEngine(model_name, force_backend=desired)
        return cls._instance

    def synth_stream(
        self,
        text: str,
        voice: str | None = None,
        temperature: float | None = None,
        repetition_penalty: float | None = None,
    ):
        """Return generator of audio byte chunks for the given text.

        - orpheus: yields 16-bit PCM chunks at 24 kHz
        - mock: yields silence chunks (24 kHz)
        - pyttsx3: not used here (non-streaming); use synthesize_to_wav instead
        """
        if self.backend == "orpheus" and self.model is not None:
            return self.model.generate_speech(
                prompt=text,
                voice=voice or settings.voice,
                temperature=temperature if temperature is not None else settings.temperature,
                repetition_penalty=(
                    repetition_penalty if repetition_penalty is not None else settings.repetition_penalty
                ),
            )

        # mock (silence) fallback
        import math

        duration_s = max(0.25, 0.25 * (len(text) / 80.0))
        total_frames = int(24000 * duration_s)
        chunk_frames = 2400  # 0.1s per chunk
        silence_chunk = b"\x00\x00" * chunk_frames
        emitted = 0
        while emitted < total_frames:
            yield silence_chunk
            emitted += chunk_frames
        return

    def synthesize_to_wav(self, text: str, out_path: str | Path, voice: Optional[str] = None) -> Path:
        """Synthesize to WAV file for non-streaming backends (pyttsx3 or piper).

        Returns the output path. Raises if called for streaming backends.
        """
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if self.backend not in {"pyttsx3", "piper", "parler"}:
            raise RuntimeError("synthesize_to_wav is only supported for non-streaming backends (pyttsx3, piper, parler)")

        # Use a temp file to avoid partial outputs, then move
        tmp_dir = Path(tempfile.gettempdir()) / "orpheus_tts_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_wav = tmp_dir / f"tts_{os.getpid()}_{abs(hash(text)) & 0xFFFF_FFFF}.wav"

        if self.backend == "pyttsx3":
            engine = pyttsx3.init()
            chosen_voice = voice or settings.voice
            if chosen_voice:
                try:
                    engine.setProperty("voice", chosen_voice)
                except Exception:
                    pass
            engine.save_to_file(text, tmp_wav.as_posix())
            engine.runAndWait()
        elif self.backend == "piper":
            # Determine model: prefer explicit voice path if it looks like a .onnx file
            model_path: Optional[Path] = None
            if voice and Path(voice).suffix.lower() == ".onnx" and Path(voice).exists():
                model_path = Path(voice)
            else:
                if settings.piper_model is None:
                    raise RuntimeError("Piper model not configured. Set PIPER_MODEL to a .onnx voice file or pass --voice with a model path.")
                model_path = Path(settings.piper_model)
                if not model_path.exists():
                    raise RuntimeError(f"Piper model not found: {model_path}")

            piper_bin = settings.piper_bin or ("piper.exe" if os.name == "nt" else "piper")
            # If not an existing path, try resolving via PATH
            if not Path(piper_bin).exists():
                resolved = shutil.which(piper_bin)
                if resolved is None:
                    raise RuntimeError(f"Piper binary not found: {piper_bin}. Set PIPER_BIN or add to PATH.")
                piper_bin = resolved

            cmd = [piper_bin, "-m", model_path.as_posix(), "-f", tmp_wav.as_posix()]
            try:
                subprocess.run(cmd, input=text.encode("utf-8"), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as e:
                stderr = e.stderr.decode("utf-8", errors="ignore") if e.stderr else str(e)
                raise RuntimeError(f"Piper synthesis failed: {stderr}") from e
        elif self.backend == "parler":
            try:
                from transformers import AutoTokenizer  # type: ignore
                from parler_tts import ParlerTTSForConditionalGeneration  # type: ignore
            except Exception as e:
                raise RuntimeError("Parler backend unavailable. Install optional deps: pip install -r requirements-parler.txt") from e
            # Load model + tokenizer (weights cached by HF). Use CPU by default.
            tok = AutoTokenizer.from_pretrained(settings.parler_model)
            model = ParlerTTSForConditionalGeneration.from_pretrained(settings.parler_model)
            desc_ids = tok(text, return_tensors="pt")["input_ids"]
            style_prompt = (voice or settings.voice or "").strip() or "A clear, natural French voice with expressive, warm tone."
            prompt_ids = tok(style_prompt, return_tensors="pt")["input_ids"]
            import torch
            with torch.no_grad():
                gen = model.generate(desc_ids, prompt_input_ids=prompt_ids)
            # out is a FloatTensor of audio values or a ModelOutput with sequences=audio values
            try:
                import numpy as np  # type: ignore
                if hasattr(gen, "sequences"):
                    audio = gen.sequences.squeeze().cpu().float().numpy()
                else:
                    audio = gen.squeeze().cpu().float().numpy()
                sr = int(getattr(model.audio_encoder.config, "sampling_rate", 24000))
                import soundfile as sf  # type: ignore
                sf.write(tmp_wav.as_posix(), audio if audio.ndim == 1 else audio[0], sr)
            except Exception as e:
                raise RuntimeError(f"Parler synthesis failed during decode/write: {e}") from e

        try:
            tmp_wav.replace(out)
        except Exception:
            # Fallback to copy if replace fails across devices
            data = Path(tmp_wav).read_bytes()
            out.write_bytes(data)
            try:
                Path(tmp_wav).unlink(missing_ok=True)
            except Exception:
                pass
        return out


def write_stream_to_wav(chunks: Iterable[bytes], out_path: str | Path, sample_rate: int = 24000) -> None:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(out.as_posix(), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit PCM
        wf.setframerate(sample_rate)
        for ch in chunks:
            wf.writeframes(ch)


def maybe_convert_to_mp3(wav_path: str | Path, audio_format: str | None = None) -> Path:
    out = Path(wav_path)
    fmt = (audio_format or settings.audio_format).lower()
    if fmt == "mp3":
        # First try via pydub
        try:
            from pydub import AudioSegment  # type: ignore  # requires ffmpeg + (audioop/pyaudioop)

            audio = AudioSegment.from_wav(out.as_posix())
            mp3_path = out.with_suffix(".mp3")
            audio.export(mp3_path.as_posix(), format="mp3", bitrate="128k")
            try:
                out.unlink()
            except Exception:
                pass
            return mp3_path
        except Exception as e:  # pragma: no cover
            print(f"[WARN] MP3 conversion via pydub failed ({e}). Trying ffmpeg CLI...")
            # Fallback: try ffmpeg CLI directly
            try:
                ffmpeg_bin = os.getenv("FFMPEG_BIN") or ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
                if not Path(ffmpeg_bin).exists():
                    resolved = shutil.which(ffmpeg_bin)
                    if resolved:
                        ffmpeg_bin = resolved
                mp3_path = out.with_suffix(".mp3")
                cmd = [ffmpeg_bin, "-y", "-i", out.as_posix(), "-b:a", "128k", mp3_path.as_posix()]
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    out.unlink()
                except Exception:
                    pass
                return mp3_path
            except Exception as e2:
                print(f"[WARN] MP3 conversion via ffmpeg CLI failed ({e2}). Keeping WAV.")
    return out
