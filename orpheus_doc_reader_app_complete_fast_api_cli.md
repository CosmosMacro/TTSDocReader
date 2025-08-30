# TTSDocReader – Application complète (FastAPI + CLI)

Une app locale pour convertir des PDF/DOCX en audio naturel (FR) avec **Orpheus TTS**. Inclut :
- Extraction de texte (PDF via PyMuPDF, DOCX via python-docx)
- Découpage intelligent en chapitres/paragraphe
- Synthèse par blocs avec **streaming** Orpheus → WAV (option MP3 si ffmpeg/pydub)
- Contrôles : voix, température, repetition_penalty (impacte rythme), tags d’émotion
- Interface web minimaliste (FastAPI) + **CLI** pour batcher

---

## Structure du projet
```
orpheus_doc_reader/
├─ requirements.txt
├─ README.md
├─ .env.sample
├─ app/
│  ├─ __init__.py
│  ├─ config.py
│  ├─ text_extract.py
│  ├─ chunking.py
│  ├─ tts.py
│  ├─ pipeline.py
│  └─ main.py        # FastAPI (UI web + API)
└─ cli.py            # CLI : convertit un ou plusieurs fichiers
```

---

## requirements.txt
```txt
orpheus-speech>=0.1.0
fastapi>=0.111
uvicorn[standard]>=0.30
python-dotenv>=1.0
pymupdf>=1.24
python-docx>=1.1
pydub>=0.25
regex>=2024.5.15
tqdm>=4.66
```

> Remarque : `orpheus-speech` utilise `vllm` sous le capot. En cas de bug connu de vLLM (cf. README Orpheus), épinglez : `pip install vllm==0.7.3` après installation d’orpheus-speech.

---

## .env.sample
```env
# Modèle par défaut (FR finetuné)
ORPHEUS_MODEL=canopylabs/3b-fr-ft-research_release
# Dossier de sortie pour les audios
OUTPUT_DIR=outputs
# Format de sortie: wav ou mp3
AUDIO_FORMAT=wav
# Optionnel: accélérer le débit (par lissage prosodique, via temperature/repetition_penalty)
TEMPERATURE=0.7
REPETITION_PENALTY=1.15
# Voix: laissez vide pour défaut, sinon nom de la voix (selon langue/modèle)
VOICE=
```

---

## app/__init__.py
```python
# vide
```

---

## app/config.py
```python
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    model_name: str = os.getenv("ORPHEUS_MODEL", "canopylabs/3b-fr-ft-research_release")
    output_dir: str = os.getenv("OUTPUT_DIR", "outputs")
    audio_format: str = os.getenv("AUDIO_FORMAT", "wav").lower()
    temperature: float = float(os.getenv("TEMPERATURE", 0.7))
    repetition_penalty: float = float(os.getenv("REPETITION_PENALTY", 1.15))
    voice: str | None = os.getenv("VOICE") or None

settings = Settings()

os.makedirs(settings.output_dir, exist_ok=True)
```

---

## app/text_extract.py
```python
from __future__ import annotations
import re
from pathlib import Path

# PDF (PyMuPDF)
try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None

# DOCX
try:
    import docx
except ImportError:  # pragma: no cover
    docx = None

SUPPORTED_EXTS = {".pdf", ".docx", ".txt", ".md"}

HARD_BREAK = "\n\n"


def normalize_text(text: str) -> str:
    # Nettoyage simple: espaces, tirets de césure, lignes vides multiples
    text = text.replace("\r", "")
    # joindre césures en fin de ligne "-\n"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # compacter lignes isolées mais conserver les paragraphes
    lines = [ln.strip() for ln in text.splitlines()]
    paragraphs: list[str] = []
    buf: list[str] = []
    for ln in lines:
        if not ln:
            if buf:
                paragraphs.append(" ".join(buf))
                buf = []
        else:
            buf.append(ln)
    if buf:
        paragraphs.append(" ".join(buf))
    clean = (HARD_BREAK).join(p.strip() for p in paragraphs if p.strip())
    # remplace espaces multiples
    clean = re.sub(r"\s+", " ", clean)
    # restaure double sauts
    clean = clean.replace(" \n ", "\n")
    return clean.strip()


def extract_text(path: str | Path) -> str:
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError(f"Extension non supportée: {ext}")

    if ext == ".pdf":
        if fitz is None:
            raise RuntimeError("PyMuPDF n'est pas installé. `pip install pymupdf`.")
        doc = fitz.open(path.as_posix())
        pages = []
        for p in doc:
            pages.append(p.get_text("text"))
        raw = "\n".join(pages)
        return normalize_text(raw)

    if ext == ".docx":
        if docx is None:
            raise RuntimeError("python-docx n'est pas installé. `pip install python-docx`.")
        d = docx.Document(path)
        raw = "\n".join(par.text for par in d.paragraphs)
        return normalize_text(raw)

    if ext in {".txt", ".md"}:
        raw = Path(path).read_text(encoding="utf-8", errors="ignore")
        return normalize_text(raw)

    raise AssertionError("Chemin inattendu")
```

---

## app/chunking.py
```python
from __future__ import annotations
import regex as re
from typing import Iterable

# Découpage par paragraphes puis par phrases si nécessaire

PARA_SPLIT = re.compile(r"\n\n+")
SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def split_paragraphs(text: str) -> list[str]:
    paras = [p.strip() for p in PARA_SPLIT.split(text) if p.strip()]
    return paras


def chunk_text(paragraphs: list[str], max_chars: int = 1500) -> list[str]:
    """Découpe en morceaux ~max_chars sans couper trop brutalement.
    1500–1800 caractères conviennent bien pour Orpheus (évite >2048 tokens).
    """
    chunks: list[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            chunks.append(para)
        else:
            # découpe par phrases
            sentences = SENT_SPLIT.split(para)
            buf = []
            cur = 0
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                if cur + len(s) + 1 > max_chars and buf:
                    chunks.append(" ".join(buf).strip())
                    buf = [s]
                    cur = len(s) + 1
                else:
                    buf.append(s)
                    cur += len(s) + 1
            if buf:
                chunks.append(" ".join(buf).strip())
    return chunks


def iter_chunks(text: str, max_chars: int = 1500) -> Iterable[str]:
    return chunk_text(split_paragraphs(text), max_chars=max_chars)
```

---

## app/tts.py
```python
from __future__ import annotations
import wave
from pathlib import Path
from typing import Iterable, Optional

from .config import settings

# Orpheus
from orpheus_tts import OrpheusModel


class OrpheusEngine:
    _instance: Optional["OrpheusEngine"] = None

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or settings.model_name
        self.model = OrpheusModel(model_name=self.model_name, max_model_len=2048)

    @classmethod
    def instance(cls, model_name: str | None = None) -> "OrpheusEngine":
        if cls._instance is None:
            cls._instance = OrpheusEngine(model_name)
        return cls._instance

    def synth_stream(self, text: str, voice: str | None = None,
                     temperature: float | None = None,
                     repetition_penalty: float | None = None):
        """Retourne un générateur de chunks audio (bytes) pour `text`."""
        return self.model.generate_speech(
            prompt=text,
            voice=voice or settings.voice,
            temperature=temperature if temperature is not None else settings.temperature,
            repetition_penalty=(repetition_penalty if repetition_penalty is not None
                                 else settings.repetition_penalty),
        )


def write_stream_to_wav(chunks: Iterable[bytes], out_path: str | Path,
                        sample_rate: int = 24000) -> None:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(out.as_posix(), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit PCM
        wf.setframerate(sample_rate)
        for ch in chunks:
            wf.writeframes(ch)


def maybe_convert_to_mp3(wav_path: str | Path) -> Path:
    from .config import settings
    out = Path(wav_path)
    if settings.audio_format == "mp3":
        try:
            from pydub import AudioSegment  # nécessite ffmpeg
            audio = AudioSegment.from_wav(out.as_posix())
            mp3_path = out.with_suffix(".mp3")
            audio.export(mp3_path.as_posix(), format="mp3", bitrate="128k")
            out.unlink(missing_ok=True)
            return mp3_path
        except Exception as e:  # pragma: no cover
            print(f"[WARN] Conversion MP3 impossible ({e}). On garde le WAV.")
    return out
```

---

## app/pipeline.py
```python
from __future__ import annotations
from pathlib import Path
from typing import Optional
from tqdm import tqdm

from .config import settings
from .text_extract import extract_text
from .chunking import iter_chunks
from .tts import OrpheusEngine, write_stream_to_wav, maybe_convert_to_mp3


def synthesize_document(path: str | Path, voice: Optional[str] = None,
                        temperature: Optional[float] = None,
                        repetition_penalty: Optional[float] = None,
                        max_chars: int = 1500) -> Path:
    """Extrait le texte d'un document et génère un fichier audio résultant.
    Retourne le chemin du fichier audio (WAV/MP3 selon config).
    """
    path = Path(path)
    text = extract_text(path)
    chunks = list(iter_chunks(text, max_chars=max_chars))
    if not chunks:
        raise RuntimeError("Aucun texte extrait du document.")

    engine = OrpheusEngine.instance()

    # Nom de fichier de sortie
    base = path.stem
    out_wav = Path(settings.output_dir) / f"{base}.wav"

    # Génération par flux, morceau par morceau, dans un unique WAV
    import wave
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(out_wav.as_posix(), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)

        for part in tqdm(range(len(chunks)), desc="Synthèse", unit="bloc"):
            ch_text = chunks[part]
            # Lissage: forcer un point final pour une cadence plus propre
            if not ch_text.strip().endswith((".", "!", "?", "…")):
                ch_text = ch_text.strip() + "."
            stream = engine.synth_stream(
                ch_text,
                voice=voice,
                temperature=temperature,
                repetition_penalty=repetition_penalty,
            )
            for audio_chunk in stream:
                wf.writeframes(audio_chunk)

    final = maybe_convert_to_mp3(out_wav)
    return final
```

---

## app/main.py (FastAPI + UI)
```python
from __future__ import annotations
import io
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import HTMLResponse, FileResponse

from .config import settings
from .pipeline import synthesize_document

app = FastAPI(title="TTSDocReader")

INDEX_HTML = f"""
<!doctype html>
<html>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>TTSDocReader</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; }}
    .card {{ max-width: 820px; padding: 1.25rem; border: 1px solid #eee; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,.04); }}
    label {{ display:block; font-weight:600; margin-top: .75rem; }}
    input[type=file], input[type=text], input[type=number], select {{ width:100%; padding:.5rem; border:1px solid #ddd; border-radius:8px; }}
    button {{ margin-top: 1rem; padding:.75rem 1rem; border:0; border-radius:10px; background:#111; color:#fff; cursor:pointer; }}
    .hint {{ color:#666; font-size:.9rem; }}
  </style>
</head>
<body>
  <div class='card'>
    <h1>TTSDocReader</h1>
    <p class='hint'>Convertissez vos <b>PDF</b> et <b>DOCX</b> en audio naturel (FR) avec Orpheus TTS.<br/>Modèle par défaut : <code>{settings.model_name}</code>.</p>
    <form action='/synthesize' method='post' enctype='multipart/form-data'>
      <label>Fichier (PDF/DOCX/TXT/MD)</label>
      <input name='file' type='file' required />

      <label>Voix (optionnel)</label>
      <input name='voice' type='text' placeholder='ex: lea (selon modèle/langue)' />

      <label>Température</label>
      <input name='temperature' type='number' step='0.05' value='{settings.temperature}' />

      <label>Repetition penalty</label>
      <input name='repetition_penalty' type='number' step='0.01' value='{settings.repetition_penalty}' />

      <label>Taille max par bloc (caractères)</label>
      <input name='max_chars' type='number' min='500' max='3000' value='1500' />

      <button type='submit'>Synthétiser</button>
    </form>
  </div>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return INDEX_HTML


@app.post("/synthesize")
async def synthesize(
    file: UploadFile = File(...),
    voice: str | None = Form(None),
    temperature: float = Form(settings.temperature),
    repetition_penalty: float = Form(settings.repetition_penalty),
    max_chars: int = Form(1500),
):
    # Sauvegarde temporaire
    tmp_dir = Path("/tmp/orpheus_uploads")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / file.filename
    content = await file.read()
    tmp_path.write_bytes(content)

    out_path = synthesize_document(
        tmp_path,
        voice=voice or None,
        temperature=temperature,
        repetition_penalty=repetition_penalty,
        max_chars=max_chars,
    )
    return FileResponse(out_path.as_posix(), filename=out_path.name)
```

---

## cli.py
```python
from __future__ import annotations
import argparse
from pathlib import Path

from app.pipeline import synthesize_document
from app.config import settings


def main():
    p = argparse.ArgumentParser(description="TTSDocReader – CLI")
    p.add_argument("inputs", nargs="+", help="Fichiers ou dossiers à convertir")
    p.add_argument("--voice", default=settings.voice, help="Nom de voix (optionnel)")
    p.add_argument("--temperature", type=float, default=settings.temperature)
    p.add_argument("--repetition_penalty", type=float, default=settings.repetition_penalty)
    p.add_argument("--max_chars", type=int, default=1500)
    args = p.parse_args()

    to_process: list[Path] = []
    for inp in args.inputs:
        path = Path(inp)
        if path.is_file():
            to_process.append(path)
        elif path.is_dir():
            for ext in ("*.pdf", "*.docx", "*.txt", "*.md"):
                to_process.extend(path.rglob(ext))
        else:
            print(f"[WARN] Introuvable: {path}")

    if not to_process:
        print("Aucun fichier à traiter.")
        return

    for f in to_process:
        print(f"→ {f}")
        out = synthesize_document(
            f,
            voice=args.voice,
            temperature=args.temperature,
            repetition_penalty=args.repetition_penalty,
            max_chars=args.max_chars,
        )
        print(f"   ✓ Sortie: {out}")


if __name__ == "__main__":
    main()
```

---

## README.md
```md
# TTSDocReader

Convertit vos documents (PDF/DOCX/TXT/MD) en audio naturel (français) avec **Orpheus TTS**.

## Installation

```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Optionnel (si vLLM bug):
# pip install vllm==0.7.3
cp .env.sample .env  # et ajustez si besoin
```

## Utilisation – Web UI

```bash
uvicorn app.main:app --reload --port 8000
# Ouvrez http://localhost:8000
```

## Utilisation – CLI

```bash
python cli.py mon_fichier.pdf  # écrit dans outputs/mon_fichier.wav (ou .mp3)
python cli.py dossier_docs/ --voice lea --temperature 0.7 --repetition_penalty 1.15
```

## Paramètres utiles (prosodie / rythme)
- `temperature`: +haut → plus expressif/variable (parfois plus rapide)
- `repetition_penalty`: ≥1.1 requis pour stabilité (plus haut → débit un peu plus soutenu)
- `voice`: laissez vide pour la voix par défaut; sinon renseignez une voix supportée par le modèle/langue
- Emojis/tags d’émotion: vous pouvez insérer ponctuellement `<sigh>`, `<laugh>`, etc. dans le texte source si vous le souhaitez

## Notes
- Modèle par défaut: `canopylabs/3b-fr-ft-research_release` (multilingue FR finetuné)
- Licence Orpheus: Apache-2.0 (voir dépôt officiel)
- CPU: possible via implémentation llama.cpp (voir dossier `additional_inference_options/no_gpu` du repo Orpheus)
- Pour des longues heures d’audio, préférez une carte **GPU** (≥12 Go VRAM recommandé) ou l’hébergement géré (Baseten)

## Limitations & conseils
- Qualité d’extraction PDF varie selon la mise en page. PyMuPDF donne souvent d’excellents résultats; adaptez `extract_text` si besoin
- Très longs documents: ajustez `--max_chars` pour réduire le nombre d’appels
- MP3 nécessite `ffmpeg` installé (pydub)
```

---

## Démarrage rapide
1) Créez le dossier de projet, copiez ces fichiers
2) `python -m venv .venv && .venv/Scripts/activate` (Windows) ou `source .venv/bin/activate` (macOS/Linux)
3) `pip install -r requirements.txt`
4) `cp .env.sample .env` et ajustez
5) **Web** : `uvicorn app.main:app --reload --port 8000` → http://localhost:8000
   
   **ou** **CLI** : `python cli.py monfichier.pdf`

Bon build !
