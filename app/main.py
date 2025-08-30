from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

from .config import settings
from .pipeline import synthesize_document
from .piper_voices import list_piper_voices_json

app = FastAPI(title="OrpheusDocReader")

INDEX_HTML = f"""
<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>OrpheusDocReader</title>
  <link rel='preconnect' href='https://fonts.googleapis.com'>
  <link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>
  <link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap' rel='stylesheet'>
  <style>
    :root {{
      --bg: #f6f7fb;
      --bg-grad-1: #eef1f8;
      --bg-grad-2: #ffffff;
      --card: rgba(255,255,255,0.55);
      --border: rgba(0,0,0,0.08);
      --text: #0f1222;
      --muted: #6b7280;
      --accent: #6759ff;
      --accent-2: #7c3aed;
      --shadow: 0 10px 30px rgba(0,0,0,0.08);
      --radius: 16px;
      --input-bg: rgba(255,255,255,0.7);
      --input-border: rgba(0,0,0,0.07);
      --chip: rgba(103,89,255,0.12);
    }}
    [data-theme="dark"] {{
      --bg: #0d0f16;
      --bg-grad-1: #0b0d14;
      --bg-grad-2: #121521;
      --card: rgba(13,15,22,0.6);
      --border: rgba(255,255,255,0.08);
      --text: #e8eaf1;
      --muted: #9aa3b2;
      --input-bg: rgba(255,255,255,0.06);
      --input-border: rgba(255,255,255,0.1);
      --shadow: 0 10px 30px rgba(0,0,0,0.5);
      --chip: rgba(124,58,237,0.22);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; padding: 0; min-height: 100vh; color: var(--text);
      font-family: 'Inter', system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: radial-gradient(1200px 600px at 10% -10%, var(--bg-grad-1), transparent),
                  radial-gradient(1000px 800px at 100% 0%, var(--bg-grad-2), var(--bg));
      background-attachment: fixed;
    }}
    .wrap {{ max-width: 1000px; margin: 0 auto; padding: 2rem; }}
    .topbar {{ display:flex; align-items:center; justify-content:space-between; margin-bottom: 1rem; }}
    .brand {{ display:flex; align-items:center; gap:.75rem; font-weight:700; font-size:1.25rem; }}
    .chip {{ background: var(--chip); color: var(--accent); padding:.25rem .6rem; border-radius: 999px; font-size:.8rem; font-weight:600; }}
    .grid {{ display:grid; grid-template-columns: 1fr; gap: 16px; }}
    @media (min-width: 920px) {{ .grid {{ grid-template-columns: 1fr 1fr; }} .grid-wide {{ grid-column: 1 / -1; }} }}
    .card {{ background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); padding: 1rem 1.25rem 1.25rem; }}
    .card h2 {{ display:flex; align-items:center; gap:.6rem; font-size:1rem; margin: .25rem 0 1rem; }}
    .hint {{ color: var(--muted); font-size: .9rem; }}
    label {{ display:block; font-weight:600; margin-top:.75rem; margin-bottom:.25rem; }}
    input[type=file], input[type=text], input[type=number], select {{ width:100%; padding:.7rem .8rem; border-radius:12px; border: 1px solid var(--input-border); background: var(--input-bg); color: var(--text); outline: none; }}
    input[type=number]::-webkit-outer-spin-button, input[type=number]::-webkit-inner-spin-button {{ -webkit-appearance:none; margin:0; }}
    .row {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
    .row > * {{ flex:1; min-width: 180px; }}
    .toolbar {{ display:flex; gap:.75rem; align-items:center; justify-content:space-between; margin-top: .75rem; }}
    .actions {{ display:flex; gap:.75rem; align-items:center; }}
    .btn {{ appearance:none; border:1px solid transparent; padding:.8rem 1rem; border-radius: 999px; cursor:pointer; font-weight:600; transition: all .2s ease; }}
    .btn-ghost {{ background: transparent; border-color: var(--input-border); color: var(--text); }}
    .btn-ghost:hover {{ border-color: var(--accent); color: var(--accent); transform: translateY(-1px); }}
    .btn-accent {{ background: linear-gradient(135deg, var(--accent), var(--accent-2)); color:#fff; box-shadow: 0 8px 20px rgba(103,89,255,.35); }}
    .btn-accent:hover {{ filter: brightness(1.05); transform: translateY(-1px); }}
    .btn:disabled {{ opacity:.7; cursor:not-allowed; filter: grayscale(.2); }}
    .progress {{ height:10px; background: rgba(0,0,0,.06); border-radius:999px; overflow:hidden; border:1px solid var(--input-border); display:none; }}
    .progress.show {{ display:block; }}
    .bar {{ height:100%; width:0%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); transition: width .2s ease; }}
    .spinner {{ width:16px; height:16px; border:2px solid rgba(255,255,255,.6); border-top-color: #fff; border-radius:50%; display:inline-block; animation: spin 1s linear infinite; margin-left:.5rem; vertical-align: middle; }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    .output {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }}
    .audio {{ width: 100%; max-width: 420px; }}
    .error {{ color:#ef4444; font-weight:600; }}
    .hidden {{ display:none !important; }}
    .icon {{ width:18px; height:18px; opacity:.9; }}
    .title {{ display:flex; align-items:center; gap:.5rem; }}
  </style>
  <script>
    const themeKey = 'theme';
    const getPreferred = () => localStorage.getItem(themeKey) || 'light';
    const setTheme = (t) => {{ document.documentElement.setAttribute('data-theme', t); localStorage.setItem(themeKey, t); }};
    document.addEventListener('DOMContentLoaded', () => setTheme(getPreferred()));
  </script>
</head>
<body>
  <div class='wrap'>
    <div class='topbar'>
      <div class='brand'>
        <svg class='icon' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M12 3l2.5 4.33L19 9l-3 3.5L16 18l-4-1.5L8 18l.99-5.5L6 9l4.5-1.67L12 3z'/></svg>
        OrpheusDocReader <span class='chip'>TTS</span>
      </div>
      <div class='actions'>
        <button id='themeBtn' class='btn btn-ghost' type='button' title='Toggle theme'>
          <span id='themeIcon'>🌙</span>
        </button>
      </div>
    </div>
    <p class='hint'>Convert PDF/DOCX/TXT/MD to audio. Default model: <code>{settings.model_name}</code></p>
    <form id='ttsForm' class='grid grid-wide' action='/synthesize' method='post' enctype='multipart/form-data'>
      <div class='card'>
        <h2 class='title'>
          <svg class='icon' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'><path d='M4 14v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3'/><path d='M7 10l5-5 5 5'/><path d='M12 15V5'/></svg>
          File
        </h2>
        <label>Upload document</label>
        <input name='file' id='file' type='file' required />
      </div>
      <div class='card'>
        <h2 class='title'>
          <svg class='icon' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'><line x1='4' y1='21' x2='4' y2='14'/><line x1='4' y1='10' x2='4' y2='3'/><line x1='12' y1='21' x2='12' y2='12'/><line x1='12' y1='8' x2='12' y2='3'/><line x1='20' y1='21' x2='20' y2='16'/><line x1='20' y1='12' x2='20' y2='3'/><line x1='2' y1='14' x2='6' y2='14'/><line x1='10' y1='8' x2='14' y2='8'/><line x1='18' y1='16' x2='22' y2='16'/></svg>
          Backend
        </h2>
        <div class='row'>
          <div>
            <label>TTS backend</label>
            <select name='backend' id='backend'>
              <option value='auto' {'selected' if settings.tts_backend=='auto' else ''}>auto</option>
              <option value='orpheus' {'selected' if settings.tts_backend=='orpheus' else ''}>orpheus</option>
              <option value='piper' {'selected' if settings.tts_backend=='piper' else ''}>piper</option>
              <option value='pyttsx3' {'selected' if settings.tts_backend=='pyttsx3' else ''}>pyttsx3</option>
            </select>
          </div>
          <div id='langWrap'>
            <label>Language (Piper)</label>
            <select id='lang'></select>
          </div>
          <div id='pvoiceWrap'>
            <label>Voice (Piper)</label>
            <select id='pvoice'></select>
          </div>
        </div>
      </div>
      <div class='card'>
        <h2 class='title'>
          <svg class='icon' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'><path d='M12 1v11a3 3 0 0 1-6 0V1'/><path d='M19 10a7 7 0 0 1-14 0'/><line x1='12' y1='19' x2='12' y2='23'/><line x1='8' y1='23' x2='16' y2='23'/></svg>
          Voice
        </h2>
        <label>Voice (optional)</label>
        <input name='voice' id='voice' type='text' placeholder='e.g., lea (Orpheus) or C:/path/to/fr_FR-voice.onnx (Piper)' />
      </div>
      <div class='card'>
        <h2 class='title'>
          <svg class='icon' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'><circle cx='12' cy='12' r='3'/><path d='M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 7 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z'/></svg>
          Parameters
        </h2>
        <div class='row'>
          <div>
            <label>Temperature</label>
            <input name='temperature' id='temperature' type='number' step='0.05' value='{settings.temperature}' />
          </div>
          <div>
            <label>Repetition penalty</label>
            <input name='repetition_penalty' id='repetition_penalty' type='number' step='0.01' value='{settings.repetition_penalty}' />
          </div>
          <div>
            <label>Output format</label>
            <select name='audio_format' id='audio_format'>
              <option value='wav' {'selected' if settings.audio_format=='wav' else ''}>wav</option>
              <option value='mp3' {'selected' if settings.audio_format=='mp3' else ''}>mp3</option>
            </select>
          </div>
          <div>
            <label>Max block length (chars)</label>
            <input name='max_chars' id='max_chars' type='number' min='500' max='3000' value='1500' />
          </div>
        </div>
        <div class='toolbar'>
          <div class='progress' id='progress'><div class='bar' id='bar'></div></div>
          <div class='actions'>
            <button id='synthBtn' class='btn btn-accent' type='submit'>Synthesize</button>
          </div>
        </div>
      </div>
      <div class='card grid-wide'>
        <h2 class='title'>
          <svg class='icon' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'><polygon points='5 3 19 12 5 21 5 3'/></svg>
          Output
        </h2>
        <div id='output' class='output'>
          <audio id='player' class='audio hidden' controls></audio>
          <a id='download' class='btn btn-ghost hidden' download>
            <svg class='icon' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'><path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/><polyline points='7 10 12 15 17 10'/><line x1='12' y1='15' x2='12' y2='3'/></svg>
            Download
          </a>
          <span id='status' class='hint'></span>
        </div>
      </div>
    </form>
  </div>
  <script>
    const $ = (s) => document.querySelector(s);
    const backendEl = $('#backend');
    const langWrap = $('#langWrap');
    const pvoiceWrap = $('#pvoiceWrap');
    const langEl = $('#lang');
    const pvoiceEl = $('#pvoice');
    const voiceInput = $('#voice');
    const form = $('#ttsForm');
    const btn = $('#synthBtn');
    const progress = $('#progress');
    const bar = $('#bar');
    const statusEl = $('#status');
    const player = $('#player');
    const download = $('#download');
    const themeBtn = $('#themeBtn');
    const themeIcon = $('#themeIcon');
    function updateThemeIcon() {{ const t = document.documentElement.getAttribute('data-theme'); themeIcon.textContent = t === 'dark' ? '☀️' : '🌙'; }}
    themeBtn.addEventListener('click', () => {{ const cur = document.documentElement.getAttribute('data-theme') || 'light'; const next = cur === 'dark' ? 'light' : 'dark'; localStorage.setItem('theme', next); document.documentElement.setAttribute('data-theme', next); updateThemeIcon(); }});
    updateThemeIcon();
    function togglePiperUI() {{ const show = backendEl.value === 'piper'; langWrap.style.display = show ? '' : 'none'; pvoiceWrap.style.display = show ? '' : 'none'; }}
    backendEl.addEventListener('change', togglePiperUI); togglePiperUI();
    async function loadPiperVoices() {{
      try {{
        const res = await fetch('/api/piper_voices');
        const data = await res.json();
        const langs = data.languages || [];
        langEl.innerHTML = '';
        for (const item of langs) {{
          const opt = document.createElement('option');
          opt.value = item.code; opt.textContent = `${{item.code}} (${{item.count}})`;
          langEl.appendChild(opt);
        }}
        function populateVoices() {{
          const sel = langEl.value;
          pvoiceEl.innerHTML = '';
          const item = langs.find(x => x.code === sel);
          const voices = item ? item.voices : [];
          for (const v of voices) {{
            const opt = document.createElement('option');
            opt.value = v.path; opt.textContent = `${{v.name}} (${{v.quality}})`;
            pvoiceEl.appendChild(opt);
          }}
          if (voices.length > 0) {{ pvoiceEl.selectedIndex = 0; voiceInput.value = voices[0].path; }}
        }}
        langEl.addEventListener('change', populateVoices);
        pvoiceEl.addEventListener('change', () => {{ voiceInput.value = pvoiceEl.value; }});
        if (langs.length) {{ langEl.selectedIndex = 0; populateVoices(); }}
      }} catch (e) {{ console.warn('Failed to load piper voices', e); }}
    }}
    loadPiperVoices();
    function setBusy(isBusy, text) {{ btn.disabled = isBusy; if (isBusy) {{ btn.innerHTML = 'Synthesizing <span class=\"spinner\"></span>'; }} else {{ btn.textContent = 'Synthesize'; }} progress.classList.toggle('show', isBusy); if (!isBusy) {{ bar.style.width = '0%'; }} statusEl.textContent = text || ''; }}
    function parseFileName(xhr) {{ try {{ const dispo = xhr.getResponseHeader('Content-Disposition') || ''; const m = /filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)\"?/i.exec(dispo); const name = decodeURIComponent(m?.[1] || m?.[2] || '').trim(); if (name) return name; }} catch {{}} return 'output'; }}
    form.addEventListener('submit', (ev) => {{
      ev.preventDefault();
      const fd = new FormData(form);
      if (!fd.get('file')) {{ alert('Please choose a file.'); return; }}
      const xhr = new XMLHttpRequest();
      xhr.open('POST', form.action);
      xhr.responseType = 'blob';
      setBusy(true, 'Uploading...');
      xhr.upload.onprogress = (e) => {{ if (e.lengthComputable) {{ bar.style.width = ((e.loaded/e.total)*100).toFixed(1)+'%'; }} }};
      xhr.onloadstart = () => {{ bar.style.width = '5%'; }};
      xhr.onreadystatechange = () => {{ if (xhr.readyState === 2) {{ setBusy(true, 'Synthesizing...'); }} }};
      xhr.onerror = () => {{ setBusy(false, 'Network error.'); }};
      xhr.onload = () => {{ if (xhr.status >= 200 && xhr.status < 300) {{ setBusy(false, 'Done.'); const blob = xhr.response; const url = URL.createObjectURL(blob); player.src = url; player.classList.remove('hidden'); const filename = parseFileName(xhr); download.href = url; download.download = filename; download.classList.remove('hidden'); }} else {{ setBusy(false, 'Error: ' + xhr.status); }} }};
      xhr.send(fd);
    }});
  </script>
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
    backend: str | None = Form(None),
    temperature: float = Form(settings.temperature),
    repetition_penalty: float = Form(settings.repetition_penalty),
    audio_format: str = Form(settings.audio_format),
    max_chars: int = Form(1500),
):
    # Cross-platform temporary storage
    tmp_dir = Path(tempfile.gettempdir()) / "orpheus_uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename).name or "upload"
    tmp_path = tmp_dir / safe_name
    content = await file.read()
    tmp_path.write_bytes(content)

    out_path = synthesize_document(
        tmp_path,
        voice=voice or None,
        temperature=temperature,
        repetition_penalty=repetition_penalty,
        max_chars=max_chars,
        backend=(backend or settings.tts_backend),
        audio_format=audio_format,
    )
    return FileResponse(out_path.as_posix(), filename=out_path.name)


@app.get("/api/piper_voices")
async def api_piper_voices():
    return JSONResponse(list_piper_voices_json())
