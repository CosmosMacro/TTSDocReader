# OrpheusDocReader

Convert your documents (PDF/DOCX/TXT/MD) into natural-sounding audio using Orpheus TTS.

## Installation

```bash
python -m venv .venv
# Windows PowerShell
. .venv\\Scripts\\Activate.ps1
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
# If vLLM has a known issue in your setup, you may pin:
# pip install vllm==0.7.3

# Copy env and adjust as needed
copy .env.sample .env   # Windows
# cp .env.sample .env   # macOS/Linux
```

## Web UI

```bash
uvicorn app.main:app --reload --port 8000
# Open http://localhost:8000
```

## CLI

```bash
python cli.py path\\to\\file.pdf
python cli.py docs\\ --voice lea --temperature 0.7 --repetition_penalty 1.15
```

## Output & Prosody
- `audio_format`: choose `wav` (default) or `mp3`. In Web UI use the dropdown; in CLI pass `--audio_format mp3`; or set `AUDIO_FORMAT=mp3` in `.env`.
- MP3 requires `ffmpeg` (pydub). Install ffmpeg and ensure it is on your PATH.
- `temperature`: higher = more expressive/variable
- `repetition_penalty`: ~1.1+ for stability (slightly faster cadence when higher)
- `voice`: leave empty for default; otherwise provide a model-supported voice
- You can insert occasional emotion tags like `<sigh>` or `<laugh>` in source text if supported by your model

## Notes
- Default model: `canopylabs/3b-fr-ft-research_release`
- MP3 output requires `ffmpeg` (via `pydub`). If conversion fails, the app keeps the WAV and logs a warning.
- Long documents: adjust `--max_chars` to control block size
- PDF extraction quality varies by layout; PyMuPDF usually works well

## Audio backends
- `TTS_BACKEND=auto` (default): tries Orpheus first; if unavailable, uses `pyttsx3` (CPU); otherwise falls back to a silent mock.
- `TTS_BACKEND=orpheus`: forces Orpheus (GPU recommended). If init fails, will try `pyttsx3`.
- `TTS_BACKEND=pyttsx3`: forces system TTS (CPU; SAPI5 on Windows) to produce audible WAV without GPU.

- `TTS_BACKEND=piper`: uses Piper (CPU, external binary). Configure `PIPER_BIN` and `PIPER_MODEL` in `.env`.
  - `PIPER_BIN`: path or command name (e.g., `piper` or `piper.exe`)
  - `PIPER_MODEL`: path to a voice model `.onnx` (e.g., `fr_FR-<voice>-medium.onnx`)
  - You can override the model per-run by passing `--voice` with a `.onnx` path.

On Windows without NVIDIA/CUDA, set `TTS_BACKEND=pyttsx3` to guarantee sound.

For higher-quality CPU voices on Windows, install Piper and set `TTS_BACKEND=piper`.

Example (PowerShell):
```
# Assuming you downloaded piper.exe and a fr_FR model .onnx
setx PIPER_BIN "C:\\path\\to\\piper.exe"
setx PIPER_MODEL "C:\\path\\to\\models\\fr_FR-<voice>-medium.onnx"

# Or put them in .env instead of setx

# Then run
python cli.py sample.txt --voice "C:\\path\\to\\models\\fr_FR-<voice>-medium.onnx"
```

## Project structure
```
app/
  __init__.py
  config.py
  text_extract.py
  chunking.py
  tts.py
  pipeline.py
  main.py
cli.py
requirements.txt
.env.sample
README.md
docs/WSL2_Orpheus_GPU_Setup.md
```

## Quick start
1) Create and activate virtualenv; install requirements
2) Copy `.env.sample` to `.env` and adjust if needed
3) Web: `uvicorn app.main:app --reload --port 8000` then open http://localhost:8000
   
   Or CLI: `python cli.py yourfile.pdf`

## Orpheus on WSL2 (GPU)
- For a stable GPU setup on Windows, prefer WSL2 Ubuntu.
- Follow: `docs/WSL2_Orpheus_GPU_Setup.md` to install CUDA-enabled PyTorch, vLLM and run the app with `TTS_BACKEND=orpheus`.

Happy building!
