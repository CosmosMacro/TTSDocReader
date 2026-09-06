from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

from .audiobook import build_audiobook
from .books import apply_chapter_selection, apply_chapter_titles, apply_structure, classify_chapter, load_book
from .config import save_local_llm_settings, settings
from .fish_audio import FishAudioProvider, estimate_cost_usd
from .llm import propose_with_llm
from .pipeline import synthesize_document
from .piper_voices import list_piper_voices_json
from .text_diff import apply_diff, make_diff
from .text_prepare import clean_for_speech

app = FastAPI(title="TTSDocReader")

INDEX_HTML = f"""
<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>TTSDocReader</title>
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
    .cta {{ display:flex; flex-direction:column; align-items:center; gap:.75rem; margin: 8px 0 4px; }}
    .btn-cta {{ font-size:1.05rem; padding:1rem 1.5rem; }}
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
        TTSDocReader <span class='chip'>TTS</span>
      </div>
      <div class='actions'>
        <button id='themeBtn' class='btn btn-ghost' type='button' title='Toggle theme'>
          <span id='themeIcon'>🌙</span>
        </button>
      </div>
    </div>
    <p class='hint'>Convert PDF/DOCX/TXT/MD to audio. Default model: <code>{settings.model_name}</code></p>
    <form id='ttsForm' class='grid grid-wide' action='/synthesize' method='post' enctype='multipart/form-data'>
      <input type='hidden' name='voice' id='voice' />
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
              <option value='parler' {'selected' if settings.tts_backend=='parler' else ''}>parler</option>
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
          <div id='parlerWrap'>
            <label>Style prompt (Parler)</label>
            <input id='parlerPrompt' type='text' placeholder='e.g., Warm, expressive female voice, calm tone' />
          </div>
          <div id='ovoiceWrap'>
            <label>Voice (Orpheus, optional)</label>
            <input id='ovoice' type='text' placeholder='e.g., lea' />
          </div>
        </div>
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
        
      </div>
      <div class='card'>
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
        </div>
      </div>
      <div class='cta grid-wide'>
        <div class='progress' id='progress'><div class='bar' id='bar'></div></div>
        <button id='synthBtn' class='btn btn-accent btn-cta' type='submit'>Synthesize</button>
        <span id='status' class='hint'></span>
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
    const ovoiceWrap = $('#ovoiceWrap');
    const ovoiceEl = $('#ovoice');
    const parlerWrap = $('#parlerWrap');
    const parlerPrompt = $('#parlerPrompt');
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
    function toggleBackendOptions() {{
      const isPiper = backendEl.value === 'piper';
      const isOrpheus = backendEl.value === 'orpheus';
      const isParler = backendEl.value === 'parler';
      langWrap.style.display = isPiper ? '' : 'none';
      pvoiceWrap.style.display = isPiper ? '' : 'none';
      ovoiceWrap.style.display = isOrpheus ? '' : 'none';
      parlerWrap.style.display = isParler ? '' : 'none';
      if (!isPiper && !isOrpheus && !isParler) {{ voiceInput.value = ''; }}
    }}
    backendEl.addEventListener('change', toggleBackendOptions); toggleBackendOptions();
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
    ovoiceEl?.addEventListener('input', () => {{ if (backendEl.value === 'orpheus') {{ voiceInput.value = (ovoiceEl.value || '').trim(); }} }});
    parlerPrompt?.addEventListener('input', () => {{ if (backendEl.value === 'parler') {{ voiceInput.value = (parlerPrompt.value || '').trim(); }} }});
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
    return AUDIOBOOK_HTML


@app.get("/tts", response_class=HTMLResponse)
async def legacy_tts_page():
    return INDEX_HTML


AUDIOBOOK_HTML = """
<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TTSDocReader Audiobook</title>
<style>body{font-family:system-ui,sans-serif;max-width:980px;margin:2rem auto;padding:0 1rem;color:#182033}section{border:1px solid #d8dce8;border-radius:12px;padding:1rem;margin:1rem 0}label{display:block;font-weight:600;margin:.7rem 0 .25rem}input,button,textarea{font:inherit;padding:.55rem;border-radius:8px;border:1px solid #bbc2d2}input[type=text]{width:100%;box-sizing:border-box}button{cursor:pointer;background:#6759ff;color:white;border:0;margin:.35rem .35rem .35rem 0}.chapter{display:grid;grid-template-columns:auto 1fr auto;gap:.5rem;align-items:center;margin:.4rem 0;padding:.45rem;border-radius:8px}.chapter.low{background:#fff4d6}.chapter small{color:#667085}.chapter textarea{width:100%;min-height:14rem;resize:vertical;box-sizing:border-box}.group{margin:1rem 0}.group h3{margin:.5rem 0}.tools{white-space:nowrap}.preview{grid-column:2/-1;background:#f7f8fc;padding:.6rem;white-space:pre-wrap;max-height:30rem;overflow:auto}.preview[open]{min-height:30rem}.preview[open] .edit-text{height:24rem;min-height:24rem}.chapter:fullscreen{background:#fff;padding:1.25rem;display:flex;flex-direction:column;gap:.75rem;overflow:auto}.chapter:fullscreen::backdrop{background:#f8f3e8}.chapter:fullscreen .tools{flex:0 0 auto}.chapter:fullscreen .preview[open]{display:flex;flex:1;min-height:0;height:calc(100vh - 9rem);flex-direction:column;max-height:none;overflow:hidden}.chapter:fullscreen .preview[open] .edit-text{flex:1;min-height:0;height:calc(100vh - 14rem);resize:none}.chapter:fullscreen .preview[open] .diff{flex:0 0 auto;max-height:35vh;overflow:auto}.chapter:fullscreen .preview[open] button{flex:0 0 auto}.diff{margin:.75rem 0;padding:.6rem;background:#fff;border:1px solid #d8dce8}.diff-row{display:grid;grid-template-columns:auto 1fr;gap:.5rem;padding:.25rem}.diff-add{background:#d9fbe3;color:#126b32}.diff-remove{text-decoration:line-through;background:#ffe0e0;color:#9b1c1c}.diff-change{border-left:3px solid #d97706;padding-left:.5rem}.llm-settings{padding:1rem;border:1px solid #bbc2d2;border-radius:10px}.muted{color:#667085}.error{color:#b42318;font-weight:600}</style></head>
<body><h1>TTSDocReader — Audiobook</h1><p class="muted">Importe un EPUB ou un PDF textuel, vérifie rapidement la structure, puis génère les MP3 et le M4B.</p>
<section><label>Document</label><input id="file" type="file" accept=".epub,.pdf" required><button id="inspect">Analyser le document</button><label>Manifeste existant (optionnel)</label><input id="manifestFile" type="file" accept=".structure.json,.json"><button id="loadManifest" type="button">Charger le manifeste</button><div id="summary"></div></section>
<section id="settings" hidden><label>Modèle Fish Audio</label><input id="model" type="text" value="s2.1-pro-free"><label>Identifiant de voix Fish Audio (optionnel)</label><input id="voice" type="text"><div><button id="mainOnly" type="button">Contenu principal uniquement</button><button id="allNarrative" type="button">Inclure les éléments optionnels</button><button id="saveManifest" type="button">Sauvegarder le manifeste</button><button id="llmSettingsBtn" type="button">Paramètres LLM</button></div><h2>Revue de structure</h2><p class="muted">Aperçu, déplacement, fusion et séparation sont réversibles tant que tu n’as pas généré l’audiobook.</p><div id="chapters"></div><label><input id="consent" type="checkbox"> J’accepte que le texte soit envoyé à Fish Audio pour cette conversion.</label><button id="generate">Générer les MP3 et le M4B</button><p id="status" class="muted"></p></section>
<dialog id="llmDialog"><form method="dialog" class="llm-settings"><h2>Paramètres LLM</h2><label>URL du serveur compatible OpenAI</label><input id="llmBaseUrl" type="text" value="http://127.0.0.1:1234/v1"><label>Modèle</label><input id="llmModel" type="text" value="local-model"><label>Clé API (optionnelle, laissée vide pour conserver la clé actuelle)</label><input id="llmKey" type="password"><p class="muted">La clé est transmise uniquement au serveur local de TTSDocReader.</p><button id="llmSave" type="button">Enregistrer</button><button id="llmClose" type="button">Fermer</button><p id="llmStatus" class="muted"></p></form></dialog>
<script>
const $=id=>document.getElementById(id);let current=null;
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
function syncDom(){if(!current)return;current.chapters.forEach((c,i)=>{const p=document.querySelector(`.pick[data-i="${i}"]`),t=document.querySelector(`.title[data-i="${i}"]`),e=document.querySelector(`.edit-text[data-i="${i}"]`);if(p)c.selected=p.checked;if(t)c.title=t.value;if(e)c.text=e.value;if(c.review)c.review.changes.forEach(ch=>{const box=document.querySelector(`.diff-pick[data-unit="${i}"][data-id="${ch.id}"]`);if(box)ch.accepted=box.checked;});});}
function reviewHtml(c,i){if(!c.review)return '';if(!c.review.changes.length)return `<div class="diff"><b>${c.review.mode==='llm'?'Proposition IA':'Nettoyage automatique'} — aucune modification détectée</b><button type="button" data-action="cancel-review" data-i="${i}">Fermer</button></div>`;const rows=c.review.changes.map(ch=>{const old=esc(ch.original||'(suppression)'),next=esc(ch.proposed||'(aucun ajout)');return `<div class="diff-row ${ch.kind==='insert'?'diff-add':ch.kind==='delete'?'diff-remove':'diff-change'}"><input class="diff-pick" data-unit="${i}" data-id="${ch.id}" type="checkbox" ${ch.accepted?'checked':''}><span>${ch.kind==='insert'?next:ch.kind==='delete'?old:`<del>${old}</del> <ins>${next}</ins>`}</span></div>`;}).join('');return `<div class="diff"><b>${c.review.mode==='llm'?'Proposition IA':'Nettoyage automatique'} — vérifie chaque changement</b>${rows}<button type="button" data-action="all-review" data-i="${i}">Tout accepter</button><button type="button" data-action="none-review" data-i="${i}">Tout refuser</button><button type="button" data-action="apply-review" data-i="${i}">Appliquer la sélection</button><button type="button" data-action="cancel-review" data-i="${i}">Annuler</button></div>`;}
function render(){const groups={};current.chapters.forEach((c,i)=>(groups[c.group]??=[]).push({...c,i}));$('chapters').innerHTML=Object.entries(groups).map(([group,items])=>`<div class="group"><h3>${esc(group)} <small>(${items.filter(c=>c.selected).length}/${items.length} sélectionnés)</small></h3>${items.map(c=>`<div class="chapter ${c.confidence<.7?'low':''}"><input class="pick" data-i="${c.i}" type="checkbox" ${c.selected?'checked':''}><input class="title" data-i="${c.i}" type="text" value="${esc(c.title)}"><small>${esc(c.kind)} · ${Math.round(c.confidence*100)}%</small><div class="tools"><button type="button" data-action="up" data-i="${c.i}">↑</button><button type="button" data-action="down" data-i="${c.i}">↓</button><button type="button" data-action="merge" data-i="${c.i}">Fusionner ↓</button><button type="button" data-action="split" data-i="${c.i}">Séparer</button><button type="button" data-action="fullscreen" data-i="${c.i}">Plein écran</button></div><details class="preview"><summary>Aperçu du texte / Modifier le texte</summary><textarea class="edit-text" data-i="${c.i}">${esc(c.text)}</textarea><button type="button" data-action="clean" data-i="${c.i}">Nettoyer automatiquement</button><button type="button" data-action="llm" data-i="${c.i}">Proposer avec IA</button>${reviewHtml(c,c.i)}</details></div>`).join('')}</div>`).join('');}
function setSelection(predicate){syncDom();current.chapters.forEach(c=>c.selected=predicate(c));render();}
function structure(){syncDom();return current.chapters.map(c=>({title:c.title,text:c.text,selected:!!c.selected,kind:c.kind,group:c.group,confidence:c.confidence}));}
function move(i,delta){syncDom();const j=i+delta;if(j<0||j>=current.chapters.length)return;[current.chapters[i],current.chapters[j]]=[current.chapters[j],current.chapters[i]];render();}
function merge(i){syncDom();if(i>=current.chapters.length-1)return;const a=current.chapters[i],b=current.chapters[i+1];a.title=a.title+' / '+b.title;a.text=a.text+'\\n\\n'+b.text;a.selected=a.selected||b.selected;a.confidence=Math.min(a.confidence,b.confidence);current.chapters.splice(i+1,1);render();}
function split(i){syncDom();const c=current.chapters[i],at=prompt('Texte qui commence la seconde unité (copie une phrase ou un titre)');if(!at)return;const pos=c.text.indexOf(at);if(pos<=0){alert('Marqueur introuvable ou placé au début.');return;}const first=c.text.slice(0,pos).trim(),second=c.text.slice(pos).trim();if(!first||!second)return;c.text=first;current.chapters.splice(i+1,0,{...c,title:c.title+' (suite)',text:second,confidence:Math.min(c.confidence,.6)});render();}
$('chapters').onclick=async e=>{const b=e.target.closest('button[data-action]');if(!b)return;const i=Number(b.dataset.i),a=b.dataset.action,c=current.chapters[i];if(a==='up')move(i,-1);if(a==='down')move(i,1);if(a==='merge')merge(i);if(a==='split')split(i);if(a==='fullscreen'){const el=b.closest('.chapter'),preview=el.querySelector('.preview');if(preview)preview.open=true;if(el.requestFullscreen)await el.requestFullscreen();}if(a==='all-review'||a==='none-review'){syncDom();c.review.changes.forEach(ch=>ch.accepted=a==='all-review');render();}if(a==='cancel-review'){syncDom();c.text=c.review.original;delete c.review;render();$('status').textContent='Proposition annulée.';}if(a==='apply-review'){syncDom();const accepted=c.review.changes.filter(ch=>ch.accepted).map(ch=>ch.id),fd=new FormData();fd.append('original',c.review.original);fd.append('proposed',c.review.proposed);fd.append('accepted_ids',JSON.stringify(accepted));const r=await fetch('/api/audiobook/apply-diff',{method:'POST',body:fd}),d=await r.json();if(!r.ok){$('status').textContent=d.detail||'Erreur';return;}c.text=d.text;delete c.review;render();$('status').textContent='Modifications appliquées.';}if(a==='clean'||a==='llm'){syncDom();const fd=new FormData();fd.append('text',c.text);$('status').textContent=a==='clean'?'Préparation du diff…':'Proposition IA en cours…';const r=await fetch(a==='clean'?'/api/audiobook/cleanup-preview':'/api/audiobook/llm-propose',{method:'POST',body:fd}),d=await r.json();if(!r.ok){$('status').textContent=d.detail||'Erreur';return;}c.review={original:d.original,proposed:d.proposed,changes:d.changes,mode:d.mode};if(a==='clean')c.text=d.proposed;render();$('status').textContent=a==='clean'?'Nettoyage proposé dans le texte : vérifie puis applique ou annule.':'Revue disponible : accepte ou refuse chaque changement.';}};
$('llmSettingsBtn').onclick=async()=>{const r=await fetch('/api/settings/llm'),d=await r.json();$('llmBaseUrl').value=d.base_url;$('llmModel').value=d.model;$('llmKey').value='';$('llmStatus').textContent=d.api_key_configured?'Clé configurée localement.':'Aucune clé configurée.';$('llmDialog').showModal();};
$('llmClose').onclick=()=>$('llmDialog').close();
$('llmSave').onclick=async()=>{const fd=new FormData();fd.append('base_url',$('llmBaseUrl').value);fd.append('model',$('llmModel').value);fd.append('api_key',$('llmKey').value);const r=await fetch('/api/settings/llm',{method:'POST',body:fd}),d=await r.json();$('llmStatus').textContent=r.ok?'Paramètres enregistrés.':(d.detail||'Erreur');if(r.ok)setTimeout(()=>$('llmDialog').close(),500);};
 $('loadManifest').onclick=()=>{const f=$('manifestFile').files[0];if(!f)return;const reader=new FileReader();reader.onload=()=>{try{const d=JSON.parse(reader.result);if(!Array.isArray(d.units)||!d.units.length)throw new Error('Le manifeste ne contient aucune unité.');current={title:d.title||'Document',author:d.author||null,estimated_cost_usd:0,chapters:d.units.map((c,i)=>({...c,index:i+1,kind:c.kind||'unknown',group:c.group||'À vérifier',confidence:Number(c.confidence||.5),selected:Boolean(c.selected)}))};$('summary').innerHTML='<p><b>'+esc(current.title)+'</b> — manifeste chargé. Sélection : '+current.chapters.filter(c=>c.selected).length+'/'+current.chapters.length+'</p>';render();$('settings').hidden=false;}catch(e){$('summary').innerHTML='<p class="error">'+esc(e.message||'Manifeste invalide')+'</p>';}};reader.readAsText(f);};
$('inspect').onclick=async()=>{const f=$('file').files[0];if(!f)return;const fd=new FormData();fd.append('file',f);const r=await fetch('/api/audiobook/inspect',{method:'POST',body:fd});const d=await r.json();if(!r.ok){$('summary').innerHTML='<p class="error">'+esc(d.detail||'Erreur')+'</p>';return;}current=d;$('summary').innerHTML='<p><b>'+esc(d.title)+'</b> — '+d.chapters.length+' unité(s). Sélection proposée: '+d.chapters.filter(c=>c.selected).length+' · Coût total estimé: $'+d.estimated_cost_usd.toFixed(4)+'</p>';render();$('settings').hidden=false;};
$('mainOnly').onclick=()=>setSelection(c=>c.group==='Contenu principal');$('allNarrative').onclick=()=>setSelection(c=>c.kind!=='toc'&&c.kind!=='front_matter');
$('saveManifest').onclick=async()=>{const f=$('file').files[0];if(!f)return;const fd=new FormData();fd.append('file',f);fd.append('structure_json',JSON.stringify(structure()));$('status').textContent='Sauvegarde du manifeste…';const r=await fetch('/api/audiobook/manifest',{method:'POST',body:fd});const d=await r.json();if(!r.ok){$('status').textContent=d.detail||'Erreur';return;}const blob=new Blob([JSON.stringify(d.manifest,null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=f.name.replace(/[.][^.]+$/,'')+'.structure.json';a.click();$('status').textContent='Manifeste sauvegardé : '+d.path;};
$('generate').onclick=async()=>{if(!$('consent').checked){$('status').textContent='Coche le consentement avant de lancer la conversion.';return;}const f=$('file').files[0],fd=new FormData();fd.append('file',f);fd.append('model',$('model').value);fd.append('voice',$('voice').value);fd.append('structure_json',JSON.stringify(structure()));fd.append('confirm_egress','true');$('generate').disabled=true;$('status').textContent='Conversion en cours…';const r=await fetch('/api/audiobook/synthesize',{method:'POST',body:fd});if(!r.ok){const d=await r.json();$('status').textContent=d.detail||'Erreur';$('generate').disabled=false;return;}const blob=await r.blob(),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='audiobook-output.zip';a.click();$('status').textContent='Terminé — archive téléchargée.';$('generate').disabled=false;};
</script></body></html>
"""


@app.get("/audiobook", response_class=HTMLResponse)
async def audiobook_page():
    return AUDIOBOOK_HTML


@app.post("/api/audiobook/inspect")
async def inspect_audiobook(file: UploadFile = File(...), model: str = Form("s2.1-pro-free")):
    tmp_dir = Path(tempfile.mkdtemp(prefix="ttsdocr-inspect-"))
    path = tmp_dir / (Path(file.filename or "upload").name)
    path.write_bytes(await file.read())
    try:
        book = load_book(path)
        reviews = [classify_chapter(c) for c in book.chapters]
        return {"title": book.title, "author": book.author, "estimated_cost_usd": estimate_cost_usd(book.text, model), "chapters": [{"index": c.index, "title": c.title, "text": c.text, "kind": r.kind, "confidence": r.confidence, "selected": r.selected, "group": r.group} for c, r in zip(book.chapters, reviews)]}
    except (ValueError, RuntimeError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


@app.post("/api/audiobook/cleanup")
async def cleanup_audiobook_text(text: str = Form(...)):
    if not text.strip():
        return JSONResponse({"detail": "Le texte est vide."}, status_code=400)
    return {"original": text, "cleaned": clean_for_speech(text), "mode": "deterministic"}


@app.post("/api/audiobook/llm-propose")
async def llm_propose_audiobook_text(text: str = Form(...), instruction: str = Form("")):
    if not text.strip():
        return JSONResponse({"detail": "Le texte est vide."}, status_code=400)
    try:
        proposal = propose_with_llm(
            text,
            instruction.strip() or None,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
        )
        return {"original": text, "proposed": proposal, "changes": make_diff(text, proposal), "mode": "llm", "accepted": False}
    except RuntimeError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=503)


@app.post("/api/audiobook/cleanup-preview")
async def cleanup_preview_audiobook_text(text: str = Form(...)):
    if not text.strip():
        return JSONResponse({"detail": "Le texte est vide."}, status_code=400)
    cleaned = clean_for_speech(text)
    return {"original": text, "proposed": cleaned, "changes": make_diff(text, cleaned), "mode": "deterministic"}


@app.post("/api/audiobook/apply-diff")
async def apply_audiobook_diff(original: str = Form(...), proposed: str = Form(...), accepted_ids: str = Form("[]")):
    try:
        ids = json.loads(accepted_ids)
        if not isinstance(ids, list) or not all(isinstance(item, int) for item in ids):
            raise ValueError("accepted_ids must be a JSON array of integers")
        return {"text": apply_diff(original, proposed, set(ids))}
    except (ValueError, json.JSONDecodeError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


@app.get("/api/settings/llm")
async def get_llm_settings():
    return {"base_url": settings.llm_base_url, "model": settings.llm_model, "api_key_configured": bool(settings.llm_api_key)}


@app.post("/api/settings/llm")
async def update_llm_settings(
    base_url: str = Form(...),
    model: str = Form(...),
    api_key: str = Form(""),
):
    if not base_url.strip() or not model.strip():
        return JSONResponse({"detail": "URL et modèle sont obligatoires."}, status_code=400)
    settings.llm_base_url = base_url.strip()
    settings.llm_model = model.strip()
    if api_key.strip():
        settings.llm_api_key = api_key.strip()
    save_local_llm_settings()
    return {"saved": True, "base_url": settings.llm_base_url, "model": settings.llm_model, "api_key_configured": bool(settings.llm_api_key)}


@app.post("/api/audiobook/manifest")
async def save_audiobook_manifest(
    file: UploadFile = File(...),
    structure_json: str = Form("[]"),
):
    """Persist a reviewed structure locally without contacting a TTS provider."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="ttsdocr-manifest-"))
    path = tmp_dir / (Path(file.filename or "upload").name)
    path.write_bytes(await file.read())
    try:
        book = load_book(path)
        structure = json.loads(structure_json)
        if not isinstance(structure, list):
            raise ValueError("structure_json must be a JSON array")
        reviewed = apply_structure(book, structure)
        manifest = {
            "version": 1,
            "title": book.title,
            "author": book.author,
            "source_filename": path.name,
            "units": structure,
        }
        manifest_dir = Path(settings.output_dir) / "audiobooks" / "manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / f"{path.stem}.structure.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"saved": True, "path": str(manifest_path), "title": reviewed.title, "selected_units": len(reviewed.chapters), "manifest": manifest}
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


@app.post("/api/audiobook/synthesize")
async def synthesize_audiobook(
    file: UploadFile = File(...),
    model: str = Form("s2.1-pro-free"),
    voice: str | None = Form(None),
    titles_json: str = Form("[]"),
    selected_json: str = Form("[]"),
    structure_json: str = Form("[]"),
    confirm_egress: bool = Form(False),
):
    if not confirm_egress:
        return JSONResponse({"detail": "Explicit confirmation required before sending text to Fish Audio."}, status_code=400)
    api_key = os.getenv("FISH_API_KEY", "")
    if not api_key:
        return JSONResponse({"detail": "FISH_API_KEY is not configured on this computer."}, status_code=400)
    work_dir = Path(tempfile.mkdtemp(prefix="ttsdocr-audiobook-"))
    path = work_dir / (Path(file.filename or "upload").name)
    path.write_bytes(await file.read())
    try:
        book = load_book(path)
        if structure_json != "[]":
            structure = json.loads(structure_json)
            if not isinstance(structure, list):
                raise ValueError("structure_json must be a JSON array")
            book = apply_structure(book, structure)
        else:
            titles = json.loads(titles_json)
            selected = json.loads(selected_json)
            if titles:
                if not isinstance(titles, list) or not all(isinstance(t, str) for t in titles):
                    raise ValueError("titles_json must be a JSON array of strings")
                book = apply_chapter_titles(book, titles)
            if selected:
                if not isinstance(selected, list) or not all(isinstance(item, bool) for item in selected):
                    raise ValueError("selected_json must be a JSON array of booleans")
                book = apply_chapter_selection(book, selected)
        provider = FishAudioProvider(api_key, model=model, reference_id=voice or None)
        book_output_dir = Path(settings.output_dir) / "audiobooks" / path.stem
        result = build_audiobook(book, book_output_dir, provider, voice=voice or None)
        archive = work_dir / "audiobook-output.zip"
        with ZipFile(archive, "w", ZIP_DEFLATED) as z:
            for output_file in result.m4b.parent.iterdir():
                if output_file.is_file() and output_file.suffix.lower() in {".mp3", ".m4b", ".json"}:
                    z.write(output_file, output_file.name)
        return FileResponse(archive.as_posix(), filename=f"{book.title}.zip", media_type="application/zip")
    except (ValueError, RuntimeError, OSError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)




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
