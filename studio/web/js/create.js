// "Create" workspace: prompt -> script & storyboard (local LLM) -> review
// and edit the scenes -> approve -> keyframes, clips, narration, subtitles,
// final video. Nothing generates on the GPU before "Approve and generate".
import { $, $$, h, icon, toast, fmtShort, debounce } from './dom.js';
import { get, post, put } from './api.js';

const C = { catalog: null, run: null, ctx: null, tracks: [], generating: false, pending: new Map() };
const rid = () => C.run && C.run.run_id;

export async function initCreate(ctx) {
  C.ctx = ctx;
  C.catalog = await get('/api/create/catalog');
  const cat = C.catalog;
  $('#cAspect').replaceChildren(...cat.aspects.map((a) =>
    h('button', { type: 'button', 'data-v': a.value, title: a.hint, class: a.value === cat.defaults.aspect ? 'on' : '' }, a.label)));
  $('#cLanguage').replaceChildren(...cat.languages.map((l) =>
    h('button', { type: 'button', 'data-v': l.value, class: l.value === cat.defaults.language ? 'on' : '' }, l.label)));
  $('#cDuration').value = cat.defaults.duration;
  $('#cStyle').value = cat.defaults.style;
  $('#cModel').textContent = `Script and storyboard by ${cat.llm_model} (Ollama, local). Narration uses Edge TTS (online).`;
  showAspectHint();
  for (const id of ['#cAspect', '#cLanguage']) {
    $(id).addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      for (const x of $$(`${id} button`)) x.classList.toggle('on', x === b);
      showAspectHint();
    });
  }
  $('#cWrite').addEventListener('click', write);
  $('#cGenerate').addEventListener('click', generate);
  $('#cOpenFolder').addEventListener('click', () => rid() && post(`/api/create/${rid()}/open-folder`).catch(() => {}));
  for (const nav of $$('.create-ws .tabs')) {
    nav.addEventListener('click', (e) => {
      const b = e.target.closest('.tab');
      if (!b) return;
      for (const t of $$('.tab', nav)) t.classList.toggle('active', t === b);
      for (const p of $$('.pane', nav.parentElement)) p.classList.toggle('active', p.dataset.pane === b.dataset.tab);
      if (b.dataset.tab === 'recent') loadRecent();
    });
  }
  renderStages(null);
}

function showAspectHint() {
  const v = $('#cAspect .on')?.dataset.v;
  const a = C.catalog.aspects.find((x) => x.value === v);
  $('#cAspectHint').textContent = a ? a.hint : '';
}

export function setTracks(tracks) {
  C.tracks = tracks;
  const sel = $('#cMusic');
  const cur = sel.value;
  sel.replaceChildren(h('option', { value: '' }, 'No music (narration only)'),
    ...tracks.map((t) => h('option', { value: t.key }, `${t.title} · ${t.mood}`)));
  sel.value = cur;
}

/** Called when the Create workspace becomes visible. */
export async function activate() {
  refreshServices();
  if (!C.run) {
    const last = localStorage.getItem('ovs.create');
    if (last) { try { await load(last); } catch { localStorage.removeItem('ovs.create'); } }
  }
  summary();
}

async function refreshServices() {
  try {
    const s = await get('/api/create/services');
    const o = $('#svcOllama');
    o.className = `svc ${s.ollama ? 'ok' : 'off'}`;
    o.title = s.ollama ? `Ollama is running (${s.ollama_server})` : `Ollama isn't reachable at ${s.ollama_server} — start it to write scripts`;
    const c = $('#svcComfy');
    c.className = `svc ${s.comfyui ? 'ok' : s.comfyui_startable ? 'auto' : 'off'}`;
    c.title = s.comfyui ? 'ComfyUI is running' : s.comfyui_startable
      ? `ComfyUI starts automatically when you generate (${s.comfyui_dir})` : 'ComfyUI not running and not found — set COMFYUI_ROOT in studio/.env';
  } catch { /* server busy */ }
}

function summary() {
  if (!C.run) { C.ctx.setSummary('Create · describe a video to start'); $('#createTitle').textContent = 'New AI video'; $('#createLabel').textContent = ''; return; }
  const r = C.run;
  C.ctx.setSummary(`Create · ${r.scenes.length} scenes · ${fmtShort(r.total)} · ${r.aspect} · ${r.language.toUpperCase()}`);
  $('#createTitle').textContent = r.title || r.prompt.slice(0, 60);
  $('#createLabel').textContent = r.run_id;
}

async function write() {
  const prompt = $('#cPrompt').value.trim();
  if (!prompt) { toast('Describe the video first.'); $('#cPrompt').focus(); return; }
  const btn = $('#cWrite');
  btn.disabled = true;
  try {
    const id = await C.ctx.job(post('/api/create', {
      prompt, duration: parseFloat($('#cDuration').value) || 15, aspect: $('#cAspect .on')?.dataset.v || '9:16',
      style: $('#cStyle').value, language: $('#cLanguage .on')?.dataset.v || 'en', music_preset: $('#cMusic').value || null,
    }), 'Writing the script', { onProgress: () => {} });
    await load(id);
    toast('Storyboard ready. Review and edit the scenes, then approve.', 'ok');
  } catch (e) { toast(e.message, 'error', 9000); }
  finally { btn.disabled = false; refreshServices(); }
}

async function load(id) {
  C.run = await get(`/api/create/${id}`);
  localStorage.setItem('ovs.create', id);
  render();
}

function render() {
  const r = C.run;
  $('#cBoardTitle').textContent = r.title || 'Storyboard';
  $('#cBoardMeta').textContent = `  ${r.scenes.length} scenes · ${fmtShort(r.total)} · ${r.aspect} · “${r.prompt}”`;
  $('#cWarnings').hidden = !r.warnings.length;
  $('#cWarnings').textContent = `${r.warnings.length} note${r.warnings.length === 1 ? '' : 's'}`;
  $('#cWarnings').title = r.warnings.join('\n');
  renderScenes();
  renderStages(r);
  summary();
}

function aspectRatio() {
  const [w, hgt] = (C.run?.aspect || '9:16').split(':').map(Number);
  return `${w} / ${hgt}`;
}

function renderScenes() {
  const r = C.run;
  if (!r.scenes.length) {
    $('#cScenes').replaceChildren(h('div.empty', {}, icon('sparkles'), h('p', {}, 'No storyboard yet — see the stages on the right.')));
    return;
  }
  const locked = C.generating;
  $('#cScenes').replaceChildren(...r.scenes.map((s) => {
    const field = (key, label, multiline, cls) => {
      const el = multiline
        ? h('textarea', { rows: 2, spellcheck: true, disabled: locked }, s[key] || '')
        : h('input', { value: s[key] || '', spellcheck: false, disabled: locked });
      el.addEventListener('input', () => queueEdit(s.scene_number, key, el.value));
      return h('label.field', { class: cls || '' }, label, el);
    };
    const dur = h('input', { type: 'number', min: 3, max: 6, step: 0.1, value: s.duration_seconds, disabled: locked, title: '3–6 s per scene' });
    dur.addEventListener('change', () => queueEdit(s.scene_number, 'duration_seconds', parseFloat(dur.value)));
    const kf = h('div.kf', { style: `aspect-ratio:${aspectRatio()}`, title: s.keyframe ? 'Keyframe' : 'Keyframe not generated yet' },
      s.keyframe ? h('img', { src: s.keyframe, alt: '' }) : icon('image'),
      s.clip ? h('button.icon-btn.clipbtn', { title: 'Play this clip', onclick: () => playClip(s.clip) }, icon('play')) : null);
    return h('div.scene', {},
      h('div.num', {}, String(s.scene_number)), kf,
      h('div.fields', {},
        field('image_prompt', 'Image', true, 'wide'),
        field('video_motion_prompt', 'Camera / motion', false, ''),
        h('label.field', {}, 'Seconds', dur),
        field('narration_text', 'Narration', true, 'wide'),
        h('div.meta.wide', {}, ...[s.shot_size, s.camera_movement, s.mood].filter(Boolean).map((t) => h('span.chip.ghost', {}, t)))));
  }));
}

function playClip(url) {
  $('#cFinal').hidden = false;
  const v = $('#cVideo');
  v.src = url;
  v.play().catch(() => {});
  $('#cFinalWhen').textContent = 'Scene clip';
}

function queueEdit(n, key, value) {
  const cur = C.pending.get(n) || { scene_number: n };
  cur[key] = value;
  C.pending.set(n, cur);
  saveScenes();
}

const saveScenes = debounce(() => flushScenes(), 700);

/** Sends the pending scene edits now (also before approving). */
async function flushScenes() {
  if (!rid() || !C.pending.size) return;
  const scenes = [...C.pending.values()];
  C.pending.clear();
  try {
    const st = await put(`/api/create/${rid()}/scenes`, { scenes });
    const wasDone = C.run.final;
    C.run = { ...st };
    renderStages(C.run);
    summary();
    $('#cSaved').hidden = false;
    setTimeout(() => { $('#cSaved').hidden = true; }, 1200);
    if (wasDone && !st.reviewed) toast('Edited after generation: approve again to regenerate the changed scenes.');
  } catch (e) { toast(e.message, 'error'); }
}

function renderStages(r) {
  const labels = C.catalog ? C.catalog.stage_labels : {};
  const stages = r ? r.stages : Object.entries(labels).map(([key, label]) => ({ key, label, status: 'pending' }));
  $('#cStages').replaceChildren(...stages.map((s) => {
    const qc = s.qc && s.qc.total ? `${s.qc.generated ?? s.qc.total}/${s.qc.total}` : s.qc && s.qc.scene_count ? `${s.qc.scene_count} scenes` : '';
    return h('li', { class: s.status }, h('span.st'), h('span', {}, s.label), h('span.qc', {}, qc),
      s.status === 'failed' && s.error ? h('span.err', {}, s.error) : null);
  }));
  const ready = r && r.stages.find((s) => s.key === 'storyboard')?.status === 'done';
  $('#cGenerate').disabled = !ready || C.generating;
  $('#cGenerate').replaceChildren(icon(r && r.final ? 'sparkles' : 'check'),
    r && r.final ? (r.reviewed ? 'Generate again' : 'Approve and regenerate') : 'Approve and generate');
  $('#cGate').classList.toggle('ok', !!(r && r.reviewed));
  $('#cGate').lastElementChild.replaceChildren(r && r.reviewed
    ? h('span', {}, h('b', {}, 'Approved. '), 'Generated scenes are reused; only missing or edited ones run again.')
    : h('span', {}, h('b', {}, 'Review first. '), 'Nothing runs on the GPU until you approve the storyboard. ComfyUI starts automatically if needed.'));
  if (r && r.final && !C.generating) {
    $('#cFinal').hidden = false;
    const v = $('#cVideo');
    if (!v.src.includes(r.final.url)) v.src = r.final.url;
    $('#cFinalWhen').textContent = `Final video · ${r.final.updated.replace('T', ' ')}`;
  } else if (!r || !r.final) {
    $('#cFinal').hidden = true;
  }
}

async function generate() {
  if (!rid() || C.generating) return;
  await flushScenes();
  C.generating = true;
  renderScenes();
  renderStages(C.run);
  $('#cProgress').hidden = false;
  const poll = setInterval(async () => {   // keep the stage list live while the job runs
    try { const st = await get(`/api/create/${rid()}`); renderStagesLive(st); } catch { /* ignore */ }
  }, 2500);
  try {
    await C.ctx.job(post(`/api/create/${rid()}/generate`), 'Generating', {
      onProgress: (j) => { $('#cBar').style.width = `${Math.round(j.progress * 100)}%`; $('#cMsg').textContent = j.message; },
    });
    toast('Video ready.', 'ok');
  } catch (e) { toast(e.message, 'error', 10000); }
  finally {
    clearInterval(poll);
    C.generating = false;
    $('#cProgress').hidden = true;
    await load(rid());
    refreshServices();
  }
}

function renderStagesLive(st) {
  C.run = { ...C.run, stages: st.stages, scenes: st.scenes, final: st.final };
  renderStages(C.run);
  for (const [i, s] of st.scenes.entries()) {   // keyframes appear as they are generated
    const box = $$('#cScenes .scene .kf')[i];
    if (box && s.keyframe && !box.querySelector('img')) box.replaceChildren(h('img', { src: s.keyframe, alt: '' }));
  }
}

async function loadRecent() {
  let list = [];
  try { list = await get('/api/create'); } catch { /* ignore */ }
  $('#cRecent').replaceChildren(...(list.length ? list.map((r) => h('div.home-item', {
    title: r.prompt, onclick: async () => { await load(r.run_id); },
  }, h('div.t1', {}, r.prompt), h('div.t2', {}, `${r.aspect} · ${r.status}`), h('div.t3', {}, r.updated.replace('T', ' '))))
    : [h('div.empty.small', {}, 'No creations yet.')]));
}
