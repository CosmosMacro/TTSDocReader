# OrpheusDocReader — Session Notes

Status
- Platform: Windows (PowerShell), Python 3.11.6
- Virtual env: `.venv311`
- FastAPI server: runs at `http://127.0.0.1:8000`
- CLI: works end-to-end (writes WAV to `outputs/`)
- TTS engine: selectable backend via `TTS_BACKEND` (`auto|orpheus|pyttsx3`). On this machine, `pyttsx3` ensures audible output without GPU.

Key Commands
- Activate venv: `. .venv311\Scripts\Activate.ps1`
- Install deps: `pip install -r requirements.txt`
- Optional (pin vLLM): `pip install vllm==0.7.3`
- Run CLI: `python cli.py path\to\file.pdf`
- Run server: `uvicorn app.main:app --host 127.0.0.1 --port 8000`
- Stop server: end the Python process (Task Manager) or `Stop-Process -Name python -ErrorAction SilentlyContinue`

Files & Folders
- Inputs accepted: `.pdf`, `.docx`, `.txt`, `.md`
- Outputs: `outputs\<filename>.wav` (or `.mp3` if `AUDIO_FORMAT=mp3` and ffmpeg installed)
- Config: `.env` (copy from `.env.sample`)

Audio backends
- `auto` (default): tries Orpheus (GPU) then pyttsx3 (CPU), then mock (silence) as last resort.
- `orpheus`: forces Orpheus; if it fails, automatically tries pyttsx3.
- `pyttsx3`: forces system TTS (CPU), guaranteed audible without CUDA.

Enable real speech
- CPU fallback (recommended now): `pip install pyttsx3`, set `TTS_BACKEND=pyttsx3` in `.env`.
- GPU Orpheus (optional):
  - Install CUDA-enabled PyTorch:
    - `pip uninstall -y torch torchvision torchaudio`
    - `pip install --index-url https://download.pytorch.org/whl/cu121 torch torchvision torchaudio`
  - Set env for GPU in session:
    - PowerShell: `$env:SNAC_DEVICE="cuda"`; optionally `$env:CUDA_VISIBLE_DEVICES="0"`
  - Optionally pin vLLM: `pip install vllm==0.7.3`
  - Set `TTS_BACKEND=orpheus` (or leave `auto`).

Optional next steps
- Switch output to MP3: set `AUDIO_FORMAT=mp3` in `.env` (requires ffmpeg; install separately).

Transcript tip (to log future sessions)
- Start: `Start-Transcript -Path "$HOME\Documents\Code\OrpheusDocReader\session-$(Get-Date -Format yyyyMMdd-HHmm).txt" -IncludeInvocationHeader`
- Stop: `Stop-Transcript`

Resume Checklist
1) `. .venv311\Scripts\Activate.ps1`
2) `uvicorn app.main:app --host 127.0.0.1 --port 8000` (or run CLI)
3) Upload/convert files; find outputs in `outputs/`
