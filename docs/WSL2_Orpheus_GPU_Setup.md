# OrpheusDocReader — WSL2 + NVIDIA GPU (Orpheus/vLLM)

This guide sets up the project on Ubuntu under WSL2 with GPU acceleration so Orpheus (vLLM) runs properly.

## 1) Prerequisites (Windows)
- Windows 10/11 with admin rights
- NVIDIA GPU + latest Windows driver with WSL support
- PowerShell (Admin):
  - `wsl --install` (reboot if required)
  - Ensure WSL2 default: `wsl --set-default-version 2`
  - Install Ubuntu from Microsoft Store (or `wsl --install -d Ubuntu`)
- Verify GPU on Windows: `nvidia-smi`

## 2) In Ubuntu (WSL2)
Open Ubuntu (WSL2) and run:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip ffmpeg build-essential

# Verify GPU is visible inside WSL2
nvidia-smi
```

If `nvidia-smi` works in WSL2, the driver passthrough is OK.

## 3) Get the project into WSL
For best performance, keep sources in the Linux filesystem:

```bash
cd ~
# Option A: clone repo if remote exists
# git clone <your_repo_url> OrpheusDocReader && cd OrpheusDocReader

# Option B: copy from Windows path (replace with your path)
cp -r /mnt/c/Users/Shadow/Documents/Code/OrpheusDocReader ~/OrpheusDocReader
cd ~/OrpheusDocReader
```

## 4) Python environment
```bash
python3.11 -m venv .venv
source .venv/bin/activate

# Install PyTorch CUDA 12.1 (Linux wheels)
pip install --index-url https://download.pytorch.org/whl/cu121 torch torchvision torchaudio

# vLLM tends to be most stable with specific versions
pip install vllm==0.7.3

# Project deps (includes orpheus-speech)
pip install -r requirements.txt
```

Notes:
- If `orpheus-speech` pulls a different vLLM version causing issues, force it:
  ```bash
  pip uninstall -y vllm
  pip install vllm==0.7.3
  ```
- If `transformers` version conflicts occur, try pinning: `pip install 'transformers<4.45'`.

## 5) Configure for Orpheus (GPU)
Edit `.env` in project root:

```env
TTS_BACKEND=orpheus
# Optional: select GPU explicitly
# SNAC_DEVICE=cuda
# CUDA_VISIBLE_DEVICES=0
```

## 6) Run
CLI:
```bash
source .venv/bin/activate
python cli.py sample.txt
```
Web UI:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
# Then open http://localhost:8000 from Windows
```

## 7) Troubleshooting
- `ModuleNotFoundError: vllm._C` → wrong platform/wheels. Ensure you are in WSL2 Ubuntu, not Windows Python. Reinstall `vllm==0.7.3` in WSL venv.
- `torch.cuda.is_available() == False` in WSL → update Windows NVIDIA driver with WSL support; ensure `nvidia-smi` works in WSL.
- OOM / performance → close apps using GPU, reduce load, or try smaller inputs; ensure swap is configured in WSL if needed.
- No audio output → confirm `.env` `TTS_BACKEND=orpheus`. As a fallback, set `TTS_BACKEND=pyttsx3` (CPU) to verify end-to-end pipeline.

## 8) Optional
- MP3 output: set `AUDIO_FORMAT=mp3` (requires `ffmpeg`, already installed above).
- Keep sources in Linux filesystem (`~/OrpheusDocReader`) for best I/O performance.

