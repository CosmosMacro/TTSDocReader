Third-Party Assets (TTS Engines & Voices)

This folder is intentionally not tracked by git to keep the repository lean and avoid committing large binaries/models.

Recommended layout:

third_party/
  piper/
    piper/              # Piper binaries & libs (e.g., piper.exe on Windows)
    models/             # Downloaded voice .onnx files (small set you actually use)
    piper-voices/       # (Optional) Full voices repo — very large, do not commit

Using Piper (CPU TTS)
- Set `TTS_BACKEND=piper` in your `.env` (or via environment variable).
- Set `PIPER_BIN` to the Piper executable (absolute path or `piper` if on PATH).
- Set `PIPER_MODEL` to a downloaded `.onnx` voice file.

Example (.env):
  TTS_BACKEND=piper
  PIPER_BIN=C:\\path\\to\\third_party\\piper\\piper\\piper.exe
  PIPER_MODEL=C:\\path\\to\\third_party\\piper\\models\\fr_FR-siwis-medium.onnx

Where to get Piper
- Binaries (Windows/macOS/Linux): https://github.com/rhasspy/piper/releases
- Voices: https://github.com/rhasspy/piper-voices (browse to language/model and download the `.onnx` + `.onnx.json`)

Tips
- Only download a couple of voices you plan to use (e.g., one French voice). The full `piper-voices` repo is very large.
- Keep everything under `third_party/piper` and point to them via `.env` so you can run locally without bloating the git repo.
- Do NOT commit binaries/models; this folder is ignored by `.gitignore`.

