from __future__ import annotations

from pathlib import Path
from typing import Optional

from tqdm import tqdm

from .config import settings
from .text_extract import extract_text
from .chunking import iter_chunks
from .tts import OrpheusEngine, maybe_convert_to_mp3, write_stream_to_wav


def synthesize_document(
    path: str | Path,
    voice: Optional[str] = None,
    temperature: Optional[float] = None,
    repetition_penalty: Optional[float] = None,
    max_chars: int = 1500,
    backend: Optional[str] = None,
    audio_format: Optional[str] = None,
) -> Path:
    """Extract text and synthesize an audio file (WAV/MP3 depending on config).

    Returns the output path.
    """
    p = Path(path)
    text = extract_text(p)
    # Choose chunk length; Parler is heavy on CPU, keep chunks smaller
    local_max = max_chars
    if engine.backend == "parler":
        local_max = min(max_chars, 300)
    chunks = list(iter_chunks(text, max_chars=local_max))
    if not chunks:
        raise RuntimeError("No text extracted from the document.")

    engine = OrpheusEngine.instance(force_backend=backend)

    base = p.stem
    out_wav = Path(settings.output_dir) / f"{base}.wav"

    if engine.backend in {"pyttsx3", "piper"}:
        # Non-streaming path: synthesize whole text at once
        full_text = " ".join(
            (c if c.endswith((".", "!", "?", ":")) else c + ".")
            for c in chunks
        )
        out_path = engine.synthesize_to_wav(full_text, out_wav, voice=voice)
        return maybe_convert_to_mp3(out_path, audio_format=audio_format)
    elif engine.backend == "parler":
        # Generate per-chunk audio and append to a single WAV for faster, predictable latency
        import numpy as np  # type: ignore
        import wave
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        # First chunk determines sample rate
        sr = None
        with wave.open(out_wav.as_posix(), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit PCM
            for i, ch in enumerate(chunks):
                ch_text = ch.strip()
                if not ch_text:
                    continue
                if not ch_text.endswith((".", "!", "?", ":")):
                    ch_text += "."
                audio_f32, this_sr = engine.parler_generate_audio(ch_text, voice=voice)
                if sr is None:
                    sr = this_sr
                    wf.setframerate(sr)
                # Resample if a chunk returned different SR (unlikely) — simplistic guard
                if this_sr != sr:
                    # naive resample via numpy (fallback) — keep simple to avoid extra deps
                    ratio = float(sr) / float(this_sr)
                    idx = np.arange(0, len(audio_f32) * ratio, ratio)
                    idx = idx[idx < len(audio_f32)].astype(np.int64)
                    audio_f32 = audio_f32[idx]
                # Convert to int16 PCM and write
                pcm = np.clip(audio_f32, -1.0, 1.0)
                pcm = (pcm * 32767.0).astype(np.int16).tobytes()
                wf.writeframes(pcm)
        return maybe_convert_to_mp3(out_wav, audio_format=audio_format)
    else:
        # Streaming path (orpheus or mock)
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        import wave
        with wave.open(out_wav.as_posix(), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)

            for i in tqdm(range(len(chunks)), desc="Synthesis", unit="block"):
                ch_text = chunks[i].strip()
                if not ch_text.endswith((".", "!", "?", ":")):
                    ch_text += "."
                stream = engine.synth_stream(
                    ch_text,
                    voice=voice,
                    temperature=temperature,
                    repetition_penalty=repetition_penalty,
                )
                for audio_chunk in stream:
                    wf.writeframes(audio_chunk)

        final = maybe_convert_to_mp3(out_wav, audio_format=audio_format)
        return final
