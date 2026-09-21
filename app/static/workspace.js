/* TTSDocReader workspace: no framework, all server mutations are revision guarded. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = { project:null, selectedId:null, step:1, dirty:false, saving:false, savePromise:null, saveTimer:0, mutation:0, savedMutation:0, job:null, pollTimer:0, review:null, request:null, history:[], redo:[], estimateTimer:0, estimateSerial:0, estimate:null };
  const api = '/api/projects';
  const activeJob = job => job && ['queued', 'running', 'cancelling'].includes(job.status);
  let openSerial = 0;
  let startingJob = false;
  let fullscreen = false;
  const chapterErrors = new Map();
  const esc = value => String(value ?? '');
  const text = (node, value) => { node.textContent = esc(value); return node; };
  function setLoadingStatus(node, value='', busy=false, kind='', progress=null) {
    if (!node) return;
    node.replaceChildren();
    node.className=`activity-status${busy?' is-busy':''}${kind?` ${kind}`:''}`;
    node.setAttribute('role','status'); node.setAttribute('aria-live','polite');
    node.setAttribute('aria-atomic','true'); node.setAttribute('aria-busy',String(busy));
    if (busy) { const spinner=document.createElement('span'); spinner.className='loading-spinner'; spinner.setAttribute('aria-hidden','true'); node.append(spinner); }
    node.append(text(document.createElement('span'),value));
    if (busy && progress && Number.isFinite(progress.total) && progress.total > 0) {
      const bar=document.createElement('progress'); bar.className='chapter-progress'; bar.max=progress.total; bar.value=Math.min(Math.max(0,progress.completed||0),progress.total);
      bar.setAttribute('aria-label',`Chapitres terminés : ${bar.value} sur ${progress.total}`); node.append(bar);
    }
  }
  const status = (value, kind='') => { const el=$('saveState'); el.className=kind; text(el,value); $('retrySave').hidden=kind !== 'error'; };
  const err = value => { const el=$('importError'); text(el,value); };
  const currentChapter = () => state.project?.chapters.find(c => c.id === state.selectedId);
  const clone = value => JSON.parse(JSON.stringify(value));
  const chapterText = c => c.text || '';
  const isValidated = c => Boolean(c.locked);
  const isStale = c => c.audio_status === 'stale';
  const words = () => state.project?.chapters.filter(c=>c.selected).reduce((n,c)=>n + chapterText(c).trim().split(/\s+/).filter(Boolean).length,0) || 0;
  const duration = n => `${Math.max(1,Math.round(n / 150))} min env.`;

  async function request(url, options={}) {
    const response = await fetch(url, options);
    let data = null;
    try { data = await response.json(); } catch (_) { /* Some exports are not JSON. */ }
    if (!response.ok) throw new Error(data?.detail || data?.error || `Erreur HTTP ${response.status}`);
    return data;
  }
  function projectPayload() {
    const p = clone(state.project);
    // The service records bounded historical revisions itself; do not send UI snapshots.
    delete p.history;
    delete p.updated_at;
    return p;
  }
  function mergeAudio(fresh) {
    const local = state.project;
    if (!local || local.id !== fresh.id) return;
    const byId = new Map(fresh.chapters.map(c => [c.id, c]));
    local.chapters.forEach(c => {
      const remote = byId.get(c.id);
      if (!remote) return;
      const same = c.text === remote.text && c.title === remote.title &&
        local.model === fresh.model && (local.voice || '') === (fresh.voice || '');
      c.audio_status = same ? remote.audio_status : (remote.audio_url ? 'stale' : 'missing');
      if (remote.audio_url) c.audio_url = remote.audio_url; else delete c.audio_url;
      if (remote.error) c.error = remote.error; else delete c.error;
      if (!state.dirty) c.listened = remote.listened;
      if (remote.original_text !== undefined) c.original_text = remote.original_text;
    });
    local.audio_revision = fresh.audio_revision;
    local.latest_job = fresh.latest_job;
    local.export_status = state.dirty ? 'stale' : fresh.export_status;
    local.export_url = state.dirty ? null : fresh.export_url;
  }
  function changed(message='Modifications à enregistrer') {
    state.dirty = true; state.mutation++; status(message); clearTimeout(state.saveTimer);
    state.project.export_url = null;
    state.project.export_status = 'stale';
    state.saveTimer = setTimeout(() => save(), 700);
    renderStats(); scheduleEstimate(); renderGeneration();
  }
  async function save(force=false) {
    if (!state.project || (!state.dirty && !force)) return true;
    if(state.saving)return state.savePromise;
    const projectId=state.project.id, mutation = state.mutation;
    const payload = projectPayload();
    state.saving = true; status('Enregistrement…');
    state.savePromise=(async()=>{try {
      const saved = await request(`${api}/${encodeURIComponent(state.project.id)}`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      // Never replace edits made while this request was in flight.  Only adopt its
      // revision, plus authoritative audio facts which can change in the background.
      if (!state.project || state.project.id!==projectId) return true;
      if (state.mutation === mutation) { state.project.revision=saved.revision;state.project.updated_at=saved.updated_at;state.dirty=false; }
      else { state.project.revision = saved.revision; state.dirty=true; }
      mergeAudio(saved);
      renderList(); renderGeneration(); updateHistoryButtons();
      state.savedMutation=mutation; status(state.dirty?'Modifications à enregistrer':'Enregistré');
      return true;
    } catch (e) {
      status(`Échec d’enregistrement : ${e.message}. Votre brouillon local est conservé.`, 'error');
      state.dirty = true;
      return false;
    } finally { state.saving=false;state.savePromise=null;if(state.project?.id===projectId&&state.dirty&&state.mutation!==mutation){clearTimeout(state.saveTimer);state.saveTimer=setTimeout(()=>save(),0);} }})();return state.savePromise;
  }
  async function flush(){clearTimeout(state.saveTimer);do{if(state.saving)await state.savePromise;if(state.dirty&&!(await save()))return false;}while(state.saving||state.dirty);return true;}
  function snapshot(label) {
    if (!state.project) return;
    const previous = state.history.at(-1), now = Date.now();
    const coalesce = label === 'Modification manuelle' && previous?.label === label &&
      previous.chapterId === state.selectedId && now - previous.at < 1000;
    if (coalesce) previous.at = now;
    else state.history.push({label, at:now, chapterId:state.selectedId, project:projectPayload()});
    if (state.history.length > 30) state.history.shift();
    state.redo=[]; updateHistoryButtons();
  }
  function restoreSnapshot(entry) {
    const previous = state.project, revision = previous.revision;
    state.project = clone(entry.project); state.project.revision=revision;
    state.project.chapters.forEach(c => {
      const old = previous.chapters.find(item => item.id === c.id);
      if (!old) return;
      for (const field of ['audio_status','audio_url','error','listened']) {
        if (field in old) c[field] = old[field]; else delete c[field];
      }
      if (c.text !== old.text || c.title !== old.title || previous.model !== state.project.model || previous.voice !== state.project.voice) {
        markStale(c);
        if (old.locked) c.locked = false;
      }
    });
    if (!currentChapter()) state.selectedId = state.project.chapters[0]?.id || null;
    changed(`Historique : ${entry.label}`); render();
  }
  function updateHistoryButtons(){if($('undoButton'))$('undoButton').disabled=!state.history.length;if($('redoButton'))$('redoButton').disabled=!state.redo.length;}
  function undo(){const entry=state.history.pop();if(!entry)return;state.redo.push({label:'Rétablir',project:clone(state.project)});restoreSnapshot(entry);updateHistoryButtons();}
  function redo(){const entry=state.redo.pop();if(!entry)return;state.history.push({label:'Annuler rétablissement',project:clone(state.project)});restoreSnapshot(entry);updateHistoryButtons();}

  async function loadProjects(selectId) {
    try {
      const data=await request(api); const select=$('projectSelect'); select.replaceChildren(new Option('Choisir un projet…',''));
      (data.projects||[]).forEach(p=>select.add(new Option(`${p.title||p.source_filename||'Sans titre'} — ${new Date(p.updated_at||Date.now()).toLocaleDateString('fr-FR')}`,p.id)));
      if(selectId) select.value=selectId;
    } catch(e) { status(`Impossible de charger les projets : ${e.message}`,'error'); }
  }
  async function openProject(id) {
    if (!id) return;
    const serial = ++openSerial;
    if (!(await flush())) return;
    try {
      const loaded = await request(`${api}/${encodeURIComponent(id)}`);
      if (serial !== openSerial) return;
      clearTimeout(state.pollTimer); clearInterval(state.startingTimer); state.startingActivity=null; state.job = null; state.request = null; state.review = null;
      state.project = loaded; state.selectedId = loaded.chapters[0]?.id || null;
      state.history = (loaded.history || []).map(h => ({label:'Version enregistrée', project:{...projectPayload(), ...clone(h), id:loaded.id}}));
      state.redo=[]; state.dirty=false; state.estimate=null; fullscreen=false;
      $('egressConsent').checked=false; $('previewConsent').checked=false; $('previewAudio').hidden=true;
      $('retryPoll').hidden=true; $('cancelJob').hidden=true;
      $('workspace').hidden=false; $('importPanel').hidden=true; $('projectSelect').value=id;
      setStep(2); render(); updateHistoryButtons(); scheduleEstimate();
      text($('jobStatus'), loaded.latest_job?.error || '');
      if (activeJob(loaded.latest_job)) { state.job={...loaded.latest_job}; pollJob(); }
    }
    catch(e){status(e.message,'error');}
  }
  async function importDocument() {
    const file=$('documentFile').files[0]; err(''); if(!file){err('Choisissez un document à importer.');return;}
    const button=$('importButton'); button.disabled=true; status('Import du document…');
    try { const fd=new FormData();fd.append('file',file); const p=await request(api,{method:'POST',body:fd}); await loadProjects(p.id); await openProject(p.id); }
    catch(e){err(e.message);} finally {button.disabled=false;}
  }
  function setStep(step) { state.step=Number(step); document.querySelectorAll('.steps button').forEach(b=>b.classList.toggle('active',Number(b.dataset.step)===state.step)); document.querySelectorAll('.step').forEach(s=>s.classList.toggle('active',s.id===`step${state.step}`)); if(state.step===4)renderGeneration(); }
  function filterChapters() { const value=$('chapterFilter').value; return state.project.chapters.filter(c=> value==='all'||(value==='prepare'&&!c.locked&&c.selected)||(value==='validated'&&isValidated(c))||(value==='audio-errors'&&c.error)||(value==='excluded'&&!c.selected)); }
  function badges(c) { const values=[]; if(c.locked)values.push(['Validé','ok']); if(c.audio_status==='ready')values.push(['Audio prêt','ok']); if(isStale(c))values.push(['Audio obsolète','warn']); if(c.error)values.push(['Erreur audio','error']); if(!c.selected)values.push(['Exclu','']); return values; }
  function renderList() {
    const list=$('chapterList');list.replaceChildren(); if(!state.project)return;
    const all=state.project.chapters, counts={all:all.length,prepare:all.filter(c=>!c.locked&&c.selected).length,validated:all.filter(isValidated).length,'audio-errors':all.filter(c=>c.error).length,excluded:all.filter(c=>!c.selected).length};
    const labels={all:'Tous',prepare:'À préparer',validated:'Validés','audio-errors':'Erreurs audio',excluded:'Exclus'};
    text($('filterCounts'),Object.entries(counts).map(([k,n])=>`${labels[k]} : ${n}`).join(' · '));
    filterChapters().forEach(c=>{const fragment=$('chapterTemplate').content.cloneNode(true),row=fragment.querySelector('.chapter-row'),box=fragment.querySelector('input'),open=fragment.querySelector('.chapter-open'),name=fragment.querySelector('.chapter-name'),badgesEl=fragment.querySelector('.badges');row.classList.toggle('active',c.id===state.selectedId);row.classList.toggle('excluded',!c.selected);row.classList.toggle('locked',Boolean(c.locked));row.dataset.id=c.id;box.checked=!!c.selected;box.addEventListener('change',()=>{snapshot('Sélection');c.selected=box.checked;changed();renderList();if(c.id===state.selectedId)renderEditor();});text(name,c.title||'Sans titre');badges(c).forEach(([label,k])=>{const b=document.createElement('span');b.className=`badge ${k}`;text(b,label);badgesEl.append(b)});open.addEventListener('click',()=>{state.selectedId=c.id;render();});list.append(fragment);});
  }
  function editorButton(label, action, disabled=false) { const b=document.createElement('button'); b.type='button';b.dataset.action=action;b.disabled=disabled;text(b,label);return b; }
  function renderEditor() {
    const holder=$('chapterEditor'); holder.replaceChildren(); const c=currentChapter();
    holder.classList.toggle('editor-fullscreen', fullscreen && !!c?.selected);
    if(!c){holder.append(text(document.createElement('p'),'Sélectionnez un chapitre.'));return;}
    const head=document.createElement('div');head.className='editor-head';const title=document.createElement('div');title.innerHTML='<h2></h2>';text(title.querySelector('h2'),c.title||'Sans titre');title.append(text(document.createElement('p'),`${c.kind||'Chapitre'} · ${c.group||'À vérifier'}`));head.append(title);if(c.audio_url)head.append(editorButton(c.listened?'Non écouté':'Marquer écouté','listened'));holder.append(head);
    const audioControls=()=>{const controls=document.createElement('div');controls.className='chapter-tools';if(c.selected)controls.append(editorButton(c.audio_status==='ready'?'Régénérer l’audio':'Générer l’audio','generate-chapter'));if(c.audio_url){const audio=document.createElement('audio');audio.controls=true;audio.src=c.audio_url;controls.append(audio);const link=document.createElement('a');link.href=c.audio_url;link.download='';text(link,'Télécharger le MP3');controls.append(link);}return controls;};
    if(!c.selected){const p=text(document.createElement('p'),'Ce chapitre est exclu de la génération. Activez sa case dans la liste pour le préparer.');p.className='muted';holder.append(p,audioControls());return;}
    if(c.locked){const note=text(document.createElement('div'),'🔒 Texte validé : l’édition et les réorganisations sont désactivées.');note.className='locked-note';const preview=text(document.createElement('div'),chapterText(c));preview.className='readonly-text';holder.append(note,preview,audioControls(),editorButton('Déverrouiller','unlock'));return;}
    const titleLabel=document.createElement('label');text(titleLabel,'Titre du chapitre');const titleInput=document.createElement('input');titleInput.value=c.title||'';titleInput.addEventListener('change',()=>{snapshot('Titre du chapitre');c.title=titleInput.value;markStale(c);changed();renderList();});titleLabel.append(titleInput);holder.append(titleLabel);
    const tools=document.createElement('div');tools.className='chapter-tools';[['Nettoyer le texte','clean'],['Adapter à l’oral','llm'],['Scinder ici','split'],['Fusionner avec le suivant','merge'],['↑ Déplacer','up'],['↓ Déplacer','down'],['Restaurer l’original','restore'],['Valider et verrouiller','lock']].forEach(([l,a])=>tools.append(editorButton(l,a,(a==='merge'&&!nextEditable(c))||(a==='up'&&!previousEditable(c))||(a==='down'&&!nextEditable(c)))));holder.append(tools);
    const area=document.createElement('textarea');area.className='edit-text';area.setAttribute('aria-label','Texte du chapitre');area.value=chapterText(c);area.addEventListener('input',()=>{if(c.text!==area.value){snapshot('Modification manuelle');c.text=area.value;markStale(c);changed();}});holder.append(area,audioControls());if(c.error){const p=text(document.createElement('p'),c.error);p.className='error';holder.append(p);}
    tools.append(editorButton(fullscreen ? 'Quitter le plein écran' : 'Plein écran', 'fullscreen'));
    const activity = document.createElement('p'); activity.id='chapterActivity';
    tools.after(activity); updateActivity();
  }
  function nextEditable(c){const other=state.project.chapters[state.project.chapters.indexOf(c)+1];return other&&other.selected&&!other.locked?other:null;}
  function previousEditable(c){const other=state.project.chapters[state.project.chapters.indexOf(c)-1];return other&&other.selected&&!other.locked?other:null;}
  function markStale(c){if(c.audio_status==='ready')c.audio_status='stale';}
  function renderStats(){if(!state.project)return;const n=words(), estimate=state.estimate?.estimated ? `${Number(state.estimate.estimated_cost_usd).toLocaleString('fr-FR',{style:'currency',currency:'USD'})} indicatif` : (state.estimate?.warning||'estimation en attente');text($('stats'),`${state.project.chapters.filter(c=>c.selected).length}/${state.project.chapters.length} chapitres · ${n.toLocaleString('fr-FR')} mots · ${duration(n)} · coût : ${estimate}`);}
  function scheduleEstimate(){clearTimeout(state.estimateTimer);const serial=++state.estimateSerial;state.estimateTimer=setTimeout(async()=>{if(!state.project)return;const textToEstimate=state.project.chapters.filter(c=>c.selected).map(chapterText).join('\n');try{const data=await request('/api/audiobook/estimate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:textToEstimate,model:state.project.model||''})});if(serial===state.estimateSerial){state.estimate=data;renderStats();}}catch(_){if(serial===state.estimateSerial){state.estimate={warning:'estimation indisponible'};renderStats();}}},350);}
  function renderGeneration(){if(!state.project)return;const selected=state.project.chapters.filter(c=>c.selected),bad=selected.filter(c=>c.audio_status!=='ready'),list=$('generationList');text($('generationSummary'),`${selected.length} chapitre(s) sélectionné(s), ${bad.length} à générer ou régénérer.`);list.replaceChildren();selected.forEach(c=>{const row=document.createElement('div');row.className='generation-row';const info=text(document.createElement('span'),`${c.title} — ${c.audio_status==='ready'?'MP3 prêt':c.audio_status==='stale'?'MP3 obsolète':c.error||'MP3 manquant'}`);const tools=document.createElement('span');const b=editorButton(c.audio_status==='ready'?'Régénérer':'Générer','generate-id');b.dataset.id=c.id;b.disabled=!!state.job;tools.append(b);if(c.audio_url){const a=document.createElement('a');a.href=c.audio_url;a.download='';text(a,' Écouter / télécharger');tools.append(a)}row.append(info,tools);list.append(row)});text($('assemblyBlockers'),!selected.length?'Sélectionnez au moins un chapitre.':state.project.export_status==='ready'?'Export M4B prêt.':bad.length?`Assemblage indisponible : ${bad.length} MP3 manquant(s), obsolète(s) ou en erreur.`:'Les MP3 sont prêts : l’assemblage M4B est une étape séparée.');$('generateSelected').disabled=!selected.length||!!state.job;$('retryAudio').disabled=!bad.length||!!state.job;$('assembleButton').disabled=!selected.length||bad.length>0||!!state.job;$('exportLink').hidden=!state.project.export_url;if(state.project.export_url)$('exportLink').href=state.project.export_url;}
  function render(){if(!state.project)return;$('projectTitle').value=state.project.title||'';$('projectAuthor').value=state.project.author||'';$('model').value=state.project.model||'';$('voice').value=state.project.voice||'';text($('sourceInfo'),state.project.source_filename||'Document importé');renderStats();renderList();renderEditor();renderGeneration();}

  async function invokeChapter(action) {
    const c=currentChapter();if(!c)return;
    if(action==='fullscreen'){fullscreen=!fullscreen;renderEditor();return;}
    if(action==='listened'){if(!c.audio_url)return;snapshot('État d’écoute');c.listened=!c.listened;changed();renderEditor();return;}
    if(action==='unlock'){snapshot('Déverrouillage');c.locked=false;changed();render();return;}
    if(action==='lock'){snapshot('Validation');c.locked=true;changed();render();return;}
    if(action==='restore'){snapshot('Restauration de l’original');c.text=c.original_text||'';markStale(c);changed();render();return;}
    if(action==='up'||action==='down'){const other=action==='up'?previousEditable(c):nextEditable(c);if(!other)return;snapshot('Déplacement de chapitre');const i=state.project.chapters.indexOf(c),j=state.project.chapters.indexOf(other);[state.project.chapters[i],state.project.chapters[j]]=[state.project.chapters[j],state.project.chapters[i]];changed();render();return;}
    if(action==='merge'){const other=nextEditable(c);if(!other)return;snapshot('Fusion de chapitres');c.text=`${chapterText(c)}\n\n${chapterText(other)}`;c.title=`${c.title} — ${other.title}`;markStale(c);state.project.chapters.splice(state.project.chapters.indexOf(other),1);changed();render();return;}
    if(action==='split'){const area=document.querySelector('.edit-text'),position=area?.selectionStart??0;if(position<1||position>=chapterText(c).length){status('Placez le curseur à l’endroit de la séparation.','error');return;}snapshot('Scission de chapitre');const right=chapterText(c).slice(position);c.text=chapterText(c).slice(0,position);markStale(c);const copy=clone(c);copy.id=crypto.randomUUID();copy.title=`${c.title} (suite)`;copy.text=right;copy.original_text=right;copy.audio_status='missing';delete copy.audio_url;state.project.chapters.splice(state.project.chapters.indexOf(c)+1,0,copy);state.selectedId=copy.id;changed();render();return;}
    if(action==='generate-chapter') await startGeneration([c.id],false,c.audio_status==='ready'||isStale(c));
    if(action==='clean'||action==='llm') await propose(c,action);
  }
  function updateActivity() {
    const c=currentChapter(), activity=$('chapterActivity');
    if (!c || !activity) return;
    const pending=state.request;
    const matches=pending?.projectId===state.project.id && pending.id===c.id;
    const message=matches ? `${pending.mode==='llm'?'Adaptation à l’oral':'Nettoyage'} en cours — ${Math.floor((Date.now()-pending.startedAt)/1000)} s` : chapterErrors.get(`${state.project.id}/${c.id}`) || '';
    setLoadingStatus(activity,message,matches,matches?'muted':(message?'error':''));
    document.querySelectorAll('[data-action="clean"],[data-action="llm"]').forEach(b=>b.disabled=!!pending);
  }
  async function propose(c, mode) {
    if (state.request || c.locked || !c.selected) return;
    const operation={projectId:state.project.id,id:c.id,text:c.text,mode,startedAt:Date.now()};
    state.request=operation; chapterErrors.delete(`${operation.projectId}/${c.id}`); updateActivity();
    const timer=setInterval(updateActivity,1000);
    try {
      const fd=new FormData(); fd.append('text',operation.text); if(mode==='llm')fd.append('mode','oral');
      const data=await request(`/api/audiobook/${mode==='clean'?'cleanup-preview':'llm-propose'}`,{method:'POST',body:fd});
      const current=state.project?.chapters.find(ch=>ch.id===operation.id);
      if (state.request!==operation || state.project.id!==operation.projectId || !current || current.locked || !current.selected || current.text!==operation.text) {
        chapterErrors.set(`${operation.projectId}/${operation.id}`,'Proposition ignorée : le chapitre a changé pendant le traitement.'); return;
      }
      state.review={projectId:operation.projectId,id:operation.id,original:operation.text,data};
      text($('reviewError'),''); showReview(data);
    } catch(e) { chapterErrors.set(`${operation.projectId}/${operation.id}`,e.message); }
    finally { clearInterval(timer); if(state.request===operation)state.request=null; updateActivity(); }
  }
  function showReview(data){const box=$('reviewChanges');box.replaceChildren();const changes=data.changes||[];if(!changes.length)box.append(text(document.createElement('p'),'Aucune modification proposée.'));changes.forEach((change,i)=>{const row=document.createElement('label');row.className='change';const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=true;checkbox.dataset.changeId=change.id??i;row.append(checkbox,document.createTextNode(' '));const before=document.createElement('del');text(before,change.original??change.before??'');const after=document.createElement('ins');text(after,change.proposed??change.after??'');row.append(before,document.createTextNode(' → '),after);box.append(row);});$('reviewDialog').showModal();}
  async function applyReview() {
    const review=state.review; if(!review)return;
    const eligible=()=>state.project?.id===review.projectId && state.project.chapters.find(c=>c.id===review.id && !c.locked && c.selected && c.text===review.original);
    $('applyReview').disabled=true;
    try {
      if(!eligible())throw new Error('Le chapitre a changé. Fermez cette proposition et relancez la revue.');
      const data=review.data, ids=[...document.querySelectorAll('#reviewChanges input:checked')].map(i=>Number(i.dataset.changeId));
      let result={text:data.proposed};
      if(ids.length!==(data.changes||[]).length){const fd=new FormData();fd.append('original',data.original);fd.append('proposed',data.proposed);fd.append('accepted_ids',JSON.stringify(ids));result=await request('/api/audiobook/apply-diff',{method:'POST',body:fd});}
      if(state.review!==review)return;
      const c=eligible(); if(!c)throw new Error('Le chapitre a changé pendant l’application. Relancez la revue.');
      snapshot('Application de proposition'); c.text=result.text; markStale(c); changed(); render(); state.review=null;
    } catch(e) { text($('reviewError'),e.message); }
    finally { $('applyReview').disabled=false; }
  }
  async function startGeneration(ids, preview=false, force=false) {
    if(!state.project || startingJob || state.job)return;
    if(!ids.length){status('Aucun chapitre ne correspond à cette action.','error');return;}
    const projectId=state.project.id;
    if(preview && !$('previewConsent').checked){setStep(3);text($('previewStatus'),'Acceptez l’envoi de cet extrait à Fish Audio avant de générer l’aperçu.');return;}
    if(!preview && !$('egressConsent').checked){
      if(ids.length===1){
        const c=state.project.chapters.find(ch=>ch.id===ids[0]);
        if(!window.confirm(`Envoyer le texte de « ${c?.title||'ce chapitre'} » à Fish Audio pour générer son MP3 ? Cet appel peut être facturé.`))return;
      } else {setStep(4);text($('jobStatus'),'Cochez le consentement avant de générer la sélection.');return;}
    }
    startingJob=true; state.startingActivity={projectId,preview,startedAt:Date.now()};
    const updateStartingActivity=()=>{
      const activity=state.startingActivity;
      if(!activity || activity.projectId!==projectId) return;
      setLoadingStatus(preview?$('previewStatus'):$('jobStatus'),`Préparation de la génération — ${Math.floor((Date.now()-activity.startedAt)/1000)} s`,true,'muted');
    };
    updateStartingActivity(); state.startingTimer=setInterval(updateStartingActivity,1000); renderGeneration();
    try {
      if(!(await flush()))throw new Error('Enregistrement impossible : la génération n’a pas été lancée.');
      if(state.project?.id!==projectId){setLoadingStatus(preview?$('previewStatus'):$('jobStatus'),'');return;}
      setLoadingStatus(preview?$('previewStatus'):$('jobStatus'),'Vérification du moteur audio…',true,'muted');
      const caps=await capabilities();
      if(!caps?.fish_configured || !caps.ffmpeg || !caps.ffprobe)throw new Error('Vérifiez la clé Fish Audio et les outils FFmpeg dans « Voix & aperçu ».');
      const job=await request(`${api}/${projectId}/generate`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({chapter_ids:ids,confirm_egress:true,force,preview})});
      if(state.project.id!==projectId)return;
      state.job={...job,preview,startedAt:Date.now()}; pollJob();
    } catch(e) { setLoadingStatus(preview?$('previewStatus'):$('jobStatus'),e.message,false,'error'); status(e.message,'error'); }
    finally { clearInterval(state.startingTimer); state.startingTimer=0; state.startingActivity=null; startingJob=false; renderGeneration(); }
  }
  async function pollJob() {
    clearTimeout(state.pollTimer);
    if(!state.job||!state.project)return;
    const projectId=state.project.id, jobId=state.job.id;
    try {
      const job=await request(`${api}/${projectId}/jobs/${jobId}`);
      if(state.project?.id!==projectId||state.job?.id!==jobId)return;
      state.job={...state.job,...job};
      const started=Date.parse(job.created_at)||state.job.startedAt||Date.now();
      const elapsed=Math.max(0,Math.floor((Date.now()-started)/1000));
      const chapter=state.project.chapters.find(c=>c.id===job.current_chapter_id);
      const phase=job.status==='cancelling'?'Arrêt demandé après le chapitre en cours':job.kind==='assemble'?'Assemblage en cours':'Génération en cours';
      const terminal={complete:job.kind==='assemble'?'Assemblage terminé.':'Génération terminée.',cancelled:'Arrêt effectué. Les chapitres terminés sont conservés.',failed:'La tâche a échoué.'};
      const message=activeJob(job)?`${phase}${chapter?' — '+chapter.title:''} · ${job.completed||0}/${job.total||'?'} · ${elapsed} s`:job.error||terminal[job.status]||job.status;
      setLoadingStatus(state.job.preview?$('previewStatus'):$('jobStatus'),message,activeJob(job),job.status==='failed'?'error':'muted',activeJob(job)?{completed:job.completed||0,total:job.total}:null);
      $('cancelJob').hidden=!activeJob(job); $('retryPoll').hidden=true;
      text($('cancelJob'),job.status==='cancelling'?'Arrêt demandé…':'Arrêter après le chapitre en cours');
      $('cancelJob').disabled=job.status==='cancelling';
      const fresh=await request(`${api}/${projectId}`);
      if(state.project?.id!==projectId||state.job?.id!==jobId)return;
      mergeAudio(fresh);
      const wasPreview=state.job.preview;
      if(!activeJob(job)) {
        state.job=null;
        if(wasPreview&&job.result_url){$('previewAudio').src=job.result_url+'?v='+Date.now();$('previewAudio').hidden=false;}
      }
      renderList(); renderGeneration();
      if(!/INPUT|TEXTAREA/.test(document.activeElement?.tagName) && !document.querySelector('#chapterEditor audio:not([paused])'))renderEditor();
      if(activeJob(job))state.pollTimer=setTimeout(pollJob,1200);
    } catch(e) {
      if(state.project?.id!==projectId||state.job?.id!==jobId)return;
      setLoadingStatus(state.job.preview?$('previewStatus'):$('jobStatus'),`Suivi indisponible : ${e.message}. La tâche peut continuer sur le serveur.`,false,'error');
      $('retryPoll').hidden=false; $('cancelJob').hidden=false;
    }
  }
  async function assemble() {
    if(!state.project||startingJob||state.job)return;
    const projectId=state.project.id; startingJob=true; state.startingActivity={projectId,preview:false,startedAt:Date.now()};
    const updateStartingActivity=()=>{
      const activity=state.startingActivity;
      if(activity?.projectId===projectId)setLoadingStatus($('jobStatus'),`Préparation de l’assemblage — ${Math.floor((Date.now()-activity.startedAt)/1000)} s`,true,'muted');
    };
    updateStartingActivity(); state.startingTimer=setInterval(updateStartingActivity,1000); renderGeneration();
    try {
      if(!(await flush()))throw new Error('Enregistrement impossible : l’assemblage n’a pas été lancé.');
      if(state.project?.id!==projectId){setLoadingStatus($('jobStatus'),'');return;}
      const job=await request(`${api}/${projectId}/assemble`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      if(state.project.id!==projectId)return;
      state.job={...job,startedAt:Date.now()}; pollJob();
    } catch(e) { setLoadingStatus($('jobStatus'),e.message,false,'error'); }
    finally { clearInterval(state.startingTimer); state.startingTimer=0; state.startingActivity=null; startingJob=false; renderGeneration(); }
  }

  async function capabilities() {
    try {
      const d=await request(`${api}/capabilities`), missing=[];
      if(!d.fish_configured)missing.push('configurer FISH_API_KEY');
      if(!d.ffmpeg)missing.push('installer FFmpeg ou définir FFMPEG_BIN');
      if(!d.ffprobe)missing.push('installer FFprobe ou définir FFPROBE_BIN');
      text($('capabilityStatus'),missing.length?'Avant la génération : '+missing.join(' ; ')+'.':'Fish Audio et les outils audio sont prêts.');
      return d;
    } catch(e) {text($('capabilityStatus'),`Vérification indisponible : ${e.message}`);return null;}
  }
  const getPresets=()=>{try{return JSON.parse(localStorage.getItem('ttsVoicePresets')||'{}')}catch(_){return {}}};function renderPresets(){const s=$('presetSelect'),all=getPresets();s.replaceChildren(new Option('Choisir…',''));Object.keys(all).sort().forEach(n=>s.add(new Option(n,n)))}
  async function llmOpen(){try{const d=await request('/api/settings/llm');$('llmBaseUrl').value=d.base_url||'';$('llmModel').value=d.model||'';$('llmKey').value='';text($('llmStatus'),d.api_key_configured?'Clé configurée localement.':'Aucune clé configurée.');$('llmDialog').showModal()}catch(e){status(e.message,'error')}}
  async function llmAction(path,model=true){const fd=new FormData();fd.append('base_url',$('llmBaseUrl').value);if(model)fd.append('model',$('llmModel').value);fd.append('api_key',$('llmKey').value);return request(path,{method:'POST',body:fd})}
  $('importButton').onclick=importDocument;$('refreshProjects').onclick=()=>loadProjects();$('retrySave').onclick=()=>save(true);$('projectSelect').onchange=e=>openProject(e.target.value);$('documentFile').onchange=()=>{err('');text($('fileName'),$('documentFile').files[0]?.name||'ou déposez-le ici')};$('newDocument').onclick=()=>{$('workspace').hidden=true;$('importPanel').hidden=false;$('documentFile').value=''};document.querySelector('.steps').onclick=e=>{const b=e.target.closest('[data-step]');if(b)setStep(b.dataset.step)};$('chapterFilter').onchange=renderList;$('undoButton').onclick=undo;$('redoButton').onclick=redo;$('nextPrepare').onclick=()=>{const cs=state.project.chapters,start=Math.max(0,cs.findIndex(c=>c.id===state.selectedId)),c=[...cs.slice(start+1),...cs.slice(0,start+1)].find(c=>c.selected&&!c.locked);if(c){state.selectedId=c.id;render()}};$('chapterEditor').onclick=e=>{const b=e.target.closest('[data-action]');if(b)invokeChapter(b.dataset.action)};$('generationList').onclick=e=>{const b=e.target.closest('[data-action="generate-id"]');if(b)startGeneration([b.dataset.id],false,true)};
  $('mainOnly').onclick=()=>{snapshot('Sélection principale');state.project.chapters.forEach(c=>c.selected=c.group==='Contenu principal');changed();render()};$('allNarrative').onclick=()=>{snapshot('Sélection narrative');state.project.chapters.forEach(c=>c.selected=!['toc','front_matter'].includes(c.kind));changed();render()};['projectTitle','projectAuthor','model','voice'].forEach(id=>$(id).onchange=()=>{if(!state.project)return;snapshot(`Modification ${id}`);if(id==='projectTitle')state.project.title=$(id).value;else if(id==='projectAuthor')state.project.author=$(id).value;else{state.project[id]=$(id).value;state.project.chapters.forEach(markStale);$('egressConsent').checked=false;$('previewConsent').checked=false}changed();render()});
  $('previewButton').onclick=()=>{const c=currentChapter();if(c)startGeneration([c.id],true,true)};$('generateSelected').onclick=()=>startGeneration(state.project.chapters.filter(c=>c.selected).map(c=>c.id));$('retryAudio').onclick=()=>startGeneration(state.project.chapters.filter(c=>c.selected&&(c.error||c.audio_error||isStale(c))).map(c=>c.id),false,true);$('retryPoll').onclick=()=>{if(state.job){$('retryPoll').hidden=true;pollJob()}};$('cancelJob').onclick=async()=>{if(state.job)await request(`${api}/${state.project.id}/jobs/${state.job.id}/cancel`,{method:'POST'})};$('assembleButton').onclick=assemble;
  $('applyReview').onclick=async()=>{await applyReview();if(!state.review)$('reviewDialog').close()};$('reviewAll').onclick=()=>document.querySelectorAll('#reviewChanges input').forEach(x=>x.checked=true);$('reviewNone').onclick=()=>document.querySelectorAll('#reviewChanges input').forEach(x=>x.checked=false);$('reviewCopy').onclick=()=>navigator.clipboard.writeText(state.review?.data?.proposed||'');$('refreshCapabilities').onclick=capabilities;$('presetSelect').onchange=()=>{const p=getPresets()[$('presetSelect').value];if(p){$('model').value=p.model;$('voice').value=p.voice}};$('savePreset').onclick=()=>{const n=$('presetName').value.trim();if(!n)return;const p=getPresets();p[n]={model:$('model').value,voice:$('voice').value};localStorage.setItem('ttsVoicePresets',JSON.stringify(p));renderPresets()};$('deletePreset').onclick=()=>{const p=getPresets();delete p[$('presetSelect').value];localStorage.setItem('ttsVoicePresets',JSON.stringify(p));renderPresets()};$('llmSettingsBtn').onclick=llmOpen;$('llmTest').onclick=async()=>{try{text($('llmStatus'),'Test…');const d=await llmAction('/api/settings/llm/test');text($('llmStatus'),d.model_available===false?'Connexion réussie, modèle indisponible.':'Connexion réussie.')}catch(e){text($('llmStatus'),e.message)}};$('llmModelsBtn').onclick=async()=>{try{const d=await llmAction('/api/settings/llm/models',false);$('llmModels').replaceChildren(...d.models.map(m=>new Option('',m)));text($('llmStatus'),`${d.models.length} modèle(s).`)}catch(e){text($('llmStatus'),e.message)}};$('llmSave').onclick=async()=>{try{await llmAction('/api/settings/llm');$('llmKey').value='';text($('llmStatus'),'Paramètres enregistrés.')}catch(e){text($('llmStatus'),e.message)}};
  window.addEventListener('beforeunload',e=>{if(state.dirty){e.preventDefault();e.returnValue=''}});document.addEventListener('keydown',e=>{if(e.ctrlKey&&e.key.toLowerCase()==='z'&&!/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName)){e.preventDefault();e.shiftKey?redo():undo()}});renderPresets();updateHistoryButtons();capabilities();loadProjects();
  text(document.querySelector('#reviewDialog h2'),'Revue des modifications proposées');
})();
