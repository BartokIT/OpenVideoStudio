// OpenVideoStudio editor — single-page front-end over the JSON API.
import { $, $$, h, icon, hydrateIcons, toast, fmt, fmtShort, debounce, isTyping } from './dom.js';
import { get, post, put, upload, runJob } from './api.js';
import { mountTimeline } from './timeline-host.js';
import * as create from './create.js';

const S = {
  catalog: null, tracks: [], run: null, view: null, options: null,
  selected: null, shot: null, playhead: 0, playing: false, mediaFilter: 'all', online: [],
};
let TL = null;
const previewAudio = new Audio();
const runId = () => S.run && S.run.run_id;
const lookOf = (key) => S.catalog.looks.find((l) => l.value === key);

// ===================================================================== jobs
const active = new Map();

function renderActivity() {
  const box = $('#stJob');
  const jobs = [...active.values()];
  box.hidden = !jobs.length;
  if (!jobs.length) return;
  const j = jobs[jobs.length - 1];
  $('#stJobText').textContent = j.message || j.label;
  $('#stJobBar').style.width = `${Math.round((j.progress || 0) * 100)}%`;
}

/** Runs an API job with progress in the status bar (and optionally on the stage). */
async function job(started, label, { stage = false, onProgress } = {}) {
  const key = Symbol(label);
  active.set(key, { label, message: label, progress: 0 });
  renderActivity();
  if (stage) { $('#stageBusy').hidden = false; $('#stageBusyText').textContent = label; }
  try {
    return await runJob(started, (j) => {
      active.set(key, { label, message: j.message || label, progress: j.progress });
      renderActivity();
      if (stage) $('#stageBusyText').textContent = j.message || label;
      onProgress?.(j);
    });
  } finally {
    active.delete(key);
    renderActivity();
    if (stage && ![...active.values()].length) $('#stageBusy').hidden = true;
  }
}

let queue = Promise.resolve();
/** Edits run one after the other, in the order the user made them. */
function enqueue(fn) {
  const p = queue.then(fn, fn);
  queue = p.catch(() => {});
  return p.catch((e) => toast(e.message, 'error'));
}

// ===================================================================== tabs
function selectTab(nav, name) {
  for (const t of $$('.tab', nav)) t.classList.toggle('active', t.dataset.tab === name);
  for (const p of $$('.pane', nav.parentElement)) p.classList.toggle('active', p.dataset.pane === name);
}
const showTab = (side, name) => selectTab($(`.tabs[data-tabs=${side}]`), name);

function initTabs() {
  for (const nav of $$('.tabs')) {
    nav.addEventListener('click', (e) => { const b = e.target.closest('.tab'); if (b) selectTab(nav, b.dataset.tab); });
  }
}

// ================================================================ controls
function fillChoices() {
  const C = S.catalog;
  for (const sel of $$('select[data-choices]')) {
    sel.replaceChildren(...C[sel.dataset.choices].map((c) => h('option', { value: c.value ?? '' }, c.label)));
  }
  for (const seg of $$('.seg[data-choices]')) {
    seg.replaceChildren(...C[seg.dataset.choices].map((c) =>
      h('button', { type: 'button', 'data-v': c.value ?? '', title: c.hint || c.label }, c.short)));
  }
  $('#shotMotion').replaceChildren(...C.motions.map((c) => h('option', { value: c.value }, c.label)));
  $('#shotTransition').replaceChildren(...C.shot_transitions.map((c) => h('option', { value: c.value }, c.label)));
  $('#onlineMood').append(...C.moods.map((m) => h('option', { value: m }, m[0].toUpperCase() + m.slice(1))));
  $('#onlineSource').replaceChildren(...C.online_sources.map((s) =>
    h('option', { value: s.value, disabled: !s.available }, s.label + (s.available ? '' : ' — needs a key'))));
  $('#lookGrid').replaceChildren(...C.looks.map((l) =>
    h('button.look', { type: 'button', 'data-v': l.value, title: l.description, onclick: () => setOpt('look', l.value) },
      h('div.sw', { class: `sw-${l.value}${l.letterbox ? ' lb' : ''}` }), h('div.nm', {}, l.label))));
  // home form
  $('#newSort').replaceChildren(...C.sort_modes.map((c, i) =>
    h('button', { type: 'button', 'data-v': c.value, class: i === 0 ? 'on' : '', title: c.label }, c.short)));
  $('#newLook').replaceChildren(...C.looks.map((l) => h('option', { value: l.value }, l.label)));
  $('#newDuration').value = Math.round(C.default_target_duration);
}

function readOpt(el) {
  if (el.type === 'checkbox') return el.checked;
  if (el.type === 'range' || el.type === 'number') return parseFloat(el.value);
  if (el.tagName === 'SELECT') return el.value === '' ? null : el.value;
  return el.value;
}

function bindOptions() {
  for (const el of $$('[data-opt]')) {
    const k = el.dataset.opt;
    if (el.classList.contains('seg')) {
      el.addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) setOpt(k, b.dataset.v); });
    } else if (el.type === 'range') {
      el.addEventListener('input', () => showOut(k, el.value));
      el.addEventListener('change', () => setOpt(k, readOpt(el)));
    } else {
      el.addEventListener('change', () => setOpt(k, readOpt(el)));
    }
  }
}

function showOut(k, v) {
  const out = $(`[data-out=${k}]`);
  if (!out) return;
  const n = parseFloat(v);
  out.textContent = k === 'music_volume' ? `${Math.round(n * 100)}%` : `${n.toFixed(1)}×`;
}

function applyOptions() {
  const o = S.options || S.catalog.default_options;
  for (const el of $$('[data-opt]')) {
    const k = el.dataset.opt;
    const v = o[k];
    if (el.classList.contains('seg')) {
      for (const b of $$('button', el)) b.classList.toggle('on', b.dataset.v === String(v ?? ''));
    } else if (el.type === 'checkbox') el.checked = !!v;
    else if (el.type === 'range') { el.value = v; showOut(k, v); }
    else if (document.activeElement !== el) el.value = v ?? '';
  }
  for (const b of $$('#lookGrid .look')) b.classList.toggle('on', b.dataset.v === o.look);
  const l = lookOf(o.look);
  if (l) {
    $('#lookDesc').replaceChildren(h('b', {}, l.label), ' — ', l.description,
      h('div.muted', { style: 'margin-top:4px' }, `Music mood: ${l.mood} · ${l.transitions.slice(0, 5).join(', ')}…`));
  }
  const tm = S.catalog.transition_modes.find((c) => c.value === o.transition_mode);
  $('#transHint').textContent = tm ? tm.hint : '';
  $('[data-opt=music_sync]').style.opacity = o.beat_sync ? 1 : 0.4;
  renderTracks();
}

function setOpt(k, v) {
  if (!S.run) { toast('Open or create a project first.'); applyOptions(); return; }
  S.options = { ...S.options, [k]: v };
  applyOptions();
  saveOptions();
}

const saveOptions = debounce(() => enqueue(async () => {
  const id = runId();
  await job(put(`/api/runs/${id}/options`, { options: S.options, playhead: S.playhead }), 'Updating the timeline');
  if (id !== runId()) return;
  await refreshRun();
  if (S.options.music_preset && !S.options.music_preset.startsWith?.('dl:')) loadTracks();
}), 350);

// ===================================================================== run
function viewWithCursor() {
  return S.view ? { ...S.view, playhead: S.playhead, selected: S.selected } : null;
}

async function loadRun(id, { name } = {}) {
  $('#stageBusy').hidden = false;
  $('#stageBusyText').textContent = 'Opening…';
  try {
    const st = await get(`/api/runs/${id}`);
    S.run = st;
    S.view = st.view;
    S.options = st.options;
    S.playhead = st.view ? st.view.playhead : 0;
    S.selected = st.view ? st.view.selected : null;
    localStorage.setItem('ovs.run', id);
    const folderName = (st.source_folder || '').split(/[\\/]/).filter(Boolean).pop() || 'Untitled';
    if (name) localStorage.setItem(`ovs.name.${id}`, name);
    $('#projectName').value = localStorage.getItem(`ovs.name.${id}`) || folderName;
    $('#runLabel').textContent = id;
    $('#stageEmpty').hidden = true;
    applyOptions();
    renderAll();
    TL.set(viewWithCursor());
    showFrame(S.playhead);
    if (S.selected) selectShot(S.selected, { seek: false, tab: false });
    else clearInspector();
    closeHome();
  } finally {
    $('#stageBusy').hidden = true;
  }
}

/** Reloads the run after a change. fromServer: take the playhead/selection
 *  the server chose (after an edit it points at the edited shot). */
async function refreshRun({ fromServer = false, reselect = true } = {}) {
  const id = runId();
  if (!id) return;
  const st = await get(`/api/runs/${id}`);
  if (id !== runId()) return;
  S.run = st;
  S.view = st.view;
  S.options = st.options;
  if (fromServer) { S.playhead = st.view.playhead; S.selected = st.view.selected; }
  S.playhead = Math.min(S.playhead, st.view.total);
  if (S.selected && !st.view.shots.some((s) => s.id === S.selected) && !st.media.some((m) => m.id === S.selected)) S.selected = null;
  applyOptions();
  renderAll();
  TL.set(viewWithCursor());
  showFrame(S.playhead);
  if (reselect && S.selected) selectShot(S.selected, { seek: false, tab: false });
}

function renderAll() {
  renderMedia();
  renderOutputs();
  renderSummary();
}

// ============================================================== workspaces
const mode = () => document.querySelector('#app').dataset.mode || 'remix';

async function setMode(m) {
  $('#app').dataset.mode = m;
  for (const b of $$('#modeSwitch button')) b.classList.toggle('on', b.dataset.mode === m);
  localStorage.setItem('ovs.mode', m);
  if (m === 'create') {
    pause();
    closeHome();
    await create.activate();
  } else {
    renderSummary();
    if (!S.run) openHome();
  }
}

function renderSummary() {
  if (mode() === 'create') return;
  if (!S.run) { $('#stSummary').textContent = ''; return; }
  const s = S.run.summary;
  const a = S.view && S.view.audio;
  const folder = (S.run.source_folder || '').split(/[\\/]/).filter(Boolean).pop();
  $('#stSummary').textContent = `${folder} · ${s.in_film}/${s.shots} in the film · ${fmtShort(s.duration)}`
    + (a && a.tempo ? ` · ♪ ${Math.round(a.tempo)} BPM` : '');
  const l = lookOf(S.options.look);
  $('#stRight').textContent = `${l ? l.label : ''} · ${S.options.resolution}`;
  $('#tempoLabel').textContent = a && a.tempo ? `${Math.round(a.tempo)} BPM · ${a.meter}/4` : 'no music';
  $('#tcTot').textContent = fmt(S.view ? S.view.total : 0);
  $('#tcCur').textContent = fmt(S.playhead);
}

// ================================================================== monitor
let frameBusy = false;
let framePending = null;

function showFrame(t) {
  if (!runId()) return;
  framePending = t;
  if (frameBusy) return;
  frameBusy = true;
  (async () => {
    try {
      while (framePending !== null) {
        const tt = framePending;
        framePending = null;
        await fetchFrame(tt);
      }
    } finally { frameBusy = false; }
  })();
}

async function fetchFrame(t) {
  const id = runId();
  let r;
  try { r = await fetch(`/api/runs/${id}/frame?t=${t.toFixed(3)}`); } catch { return; }
  if (!r.ok || id !== runId()) return;
  const url = URL.createObjectURL(await r.blob());
  const img = $('#monImg');
  const old = img.dataset.url;
  img.src = url;
  img.dataset.url = url;
  if (old) URL.revokeObjectURL(old);
  const shotIdx = parseInt(r.headers.get('X-Frame-Shot') || '0', 10);
  const s = S.view && S.view.shots[shotIdx];
  $('#monShot').textContent = s ? `Shot ${shotIdx + 1}/${S.view.shots.length} · ${s.name}` : '';
  const tr = r.headers.get('X-Frame-Transition');
  $('#monTrans').hidden = !tr;
  $('#monTrans').textContent = tr ? `⇄ ${tr}` : '';
  const texts = r.headers.get('X-Frame-Texts');
  $('#monTexts').hidden = !texts;
  $('#monTexts').textContent = texts ? `T ${texts}` : '';
}

function seek(t, { persist = true } = {}) {
  if (!S.view) return;
  S.playhead = Math.min(Math.max(t, 0), S.view.total);
  $('#tcCur').textContent = fmt(S.playhead);
  TL.set(viewWithCursor());
  hideVideo();
  showFrame(S.playhead);
  if (persist) persistCursor();
}

const persistCursor = debounce(() => {
  if (!runId()) return;
  post(`/api/runs/${runId()}/cursor`, { playhead: S.playhead, selected: S.selected, set_selected: true }).catch(() => {});
}, 700);

function cutTimes() { return S.view ? S.view.shots.map((s) => s.start) : []; }

function stepCut(dir) {
  const cuts = cutTimes();
  const t = S.playhead;
  const target = dir < 0 ? [...cuts].reverse().find((c) => c < t - 0.05) : cuts.find((c) => c > t + 0.05);
  seek(target ?? (dir < 0 ? 0 : S.view.total));
}

// draft playback: frames as fast as the server renders them, with the music
const playAudio = $('#musicAudio');
let playToken = 0;

async function play() {
  if (!S.view || S.playing) return;
  if (S.playhead >= S.view.total - 0.05) S.playhead = 0;
  S.playing = true;
  setPlayIcon();
  hideVideo();
  const token = ++playToken;
  const start = S.playhead;
  const t0 = performance.now();
  const a = S.view.audio;
  if (S.run.audio_url && a) {
    if (playAudio.dataset.src !== S.run.audio_url) { playAudio.src = S.run.audio_url; playAudio.dataset.src = S.run.audio_url; }
    playAudio.loop = true;
    playAudio.volume = Math.min(1, (S.options.music_volume || 0.35) * 2.2);
    try { playAudio.currentTime = a.duration ? start % a.duration : start; } catch { /* not loaded yet */ }
    playAudio.play().catch(() => {});
  }
  while (S.playing && token === playToken) {
    const tick = performance.now();
    const t = start + (tick - t0) / 1000;
    if (t >= S.view.total) { pause(); seek(S.view.total); break; }
    S.playhead = t;
    $('#tcCur').textContent = fmt(t);
    TL.set(viewWithCursor());
    await fetchFrame(t);
    const spent = performance.now() - tick;   // at most ~30 frames a second: enough for a draft
    if (spent < 33) await new Promise((r) => setTimeout(r, 33 - spent));
  }
}

function pause() {
  if (!S.playing) return;
  S.playing = false;
  playToken++;
  playAudio.pause();
  setPlayIcon();
  persistCursor();
}

function setPlayIcon() {
  const b = $('#tPlay');
  b.replaceChildren(icon(S.playing ? 'pause' : 'play'));
}

function playVideoInMonitor(url, label) {
  pause();
  const v = $('#monVideo');
  v.src = url;
  v.hidden = false;
  v.controls = true;
  $('#closeVideo').hidden = false;
  $('#monCut').hidden = !label;
  $('#monCut').textContent = label || '';
  v.play().catch(() => {});
}

function hideVideo() {
  const v = $('#monVideo');
  if (v.hidden) return;
  v.pause();
  v.hidden = true;
  $('#closeVideo').hidden = true;
  $('#monCut').hidden = true;
}

// ==================================================================== shot
function clearInspector() {
  S.shot = null;
  $('#shotEmpty').hidden = false;
  $('#shotForm').hidden = true;
}

async function selectShot(id, { seek: doSeek = true, tab = true } = {}) {
  if (!runId()) return;
  S.selected = id;
  TL.set(viewWithCursor());
  markMedia();
  let info;
  try { info = await get(`/api/runs/${runId()}/shots/${id}`); } catch (e) { toast(e.message, 'error'); return; }
  if (S.selected !== id) return;
  S.shot = info;
  renderInspector(info);
  if (tab) showTab('right', 'shot');
  if (doSeek && info.preview_t != null) seek(info.preview_t);
  else persistCursor();
}

function renderInspector(i) {
  $('#shotEmpty').hidden = true;
  $('#shotForm').hidden = false;
  $('#shotThumb').src = i.thumb || '';
  $('#shotName').textContent = i.name;
  $('#shotMeta').textContent = `${i.folder} · ${i.type === 'video' ? 'video' : `photo · quality ${i.score}`}`;
  const tl = i.timeline;
  $('#shotWhen').replaceChildren(tl
    ? h('span', {}, h('span.mono', {}, `${fmt(tl.start)} → ${fmt(tl.end)}`),
      h('span.muted', {}, `  ·  shot ${tl.index + 1}/${tl.count}`),
      tl.transition_in ? h('span.muted', {}, `  ·  in: ${tl.transition_in.label}${tl.transition_in.chosen ? ' (yours)' : ''}`) : '')
    : h('span.muted', {}, 'Not in the film'));
  $('#shotEnabled').checked = i.enabled;
  $('#shotExcluded').hidden = !i.excluded;
  $('#shotExcluded').textContent = i.excluded || '';
  $('#shotDuration').value = (tl ? tl.duration : i.duration).toFixed(2);
  $('#shotLock').textContent = i.duration_locked ? '· yours' : (tl && Math.abs(tl.duration - i.duration) > 0.02 ? '· on the music' : '');
  $('#shotMotion').value = i.motion || '';
  $('#shotMotion').disabled = i.type === 'video';
  $('#shotTransition').value = i.transition || '';
  $('#shotTransition').disabled = !tl || tl.index === 0;
  if (document.activeElement !== $('#shotText')) $('#shotText').value = i.text || '';
  $('#shotTextHint').textContent = i.hide_text
    ? `Text hidden here. Type “${i.auto_title}” to bring back the folder title.`
    : i.auto_title ? `Chapter title from the folder: “${i.auto_title}”. Empty the field to remove it.` : '';
  for (const id of ['shotEarlier', 'shotLater']) $(`#${id}`).disabled = !i.enabled;
  $('#shotCut').disabled = !tl || tl.index === 0;
}

function edit(action, shotId, payload = {}, label = 'Updating') {
  return enqueue(async () => {
    const id = runId();
    await job(post(`/api/runs/${id}/edit`, { action, shot_id: shotId, payload }), label, { stage: false });
    if (id !== runId()) return;
    await refreshRun({ fromServer: true, reselect: false });
    if (!S.selected) { S.selected = shotId; }
    await selectShot(S.selected, { seek: false, tab: false });
  });
}

function bindInspector() {
  const sid = () => S.shot && S.shot.id;
  $('#shotEnabled').addEventListener('change', (e) => edit('update', sid(), { enabled: e.target.checked }));
  $('#shotDuration').addEventListener('change', (e) => edit('update', sid(), { duration: parseFloat(e.target.value) }));
  $('#shotMotion').addEventListener('change', (e) => edit('update', sid(), { motion: e.target.value }));
  $('#shotTransition').addEventListener('change', (e) => edit('update', sid(), { transition: e.target.value }));
  $('#shotText').addEventListener('change', (e) => edit('update', sid(), { text: e.target.value }));
  $('#shotText').addEventListener('keydown', (e) => { if (e.key === 'Enter') e.target.blur(); });
  $('#shotEarlier').addEventListener('click', () => edit('move_by', sid(), { delta: -1 }, 'Moving'));
  $('#shotLater').addEventListener('click', () => edit('move_by', sid(), { delta: 1 }, 'Moving'));
  $('#shotCut').addEventListener('click', async () => {
    try {
      const r = await job(post(`/api/runs/${runId()}/cut/${sid()}`), 'Rendering the cut', { stage: true });
      playVideoInMonitor(r.url, r.label);
    } catch (e) { toast(e.message, 'error'); }
  });
}

// =================================================================== media
function renderMedia() {
  const grid = $('#mediaGrid');
  const media = S.run ? S.run.media : [];
  $('#cntAll').textContent = media.length;
  $('#cntIn').textContent = media.filter((m) => m.enabled).length;
  $('#cntOut').textContent = media.filter((m) => !m.enabled).length;
  const f = S.mediaFilter;
  const list = media.filter((m) => f === 'all' || (f === 'in' ? m.enabled : !m.enabled));
  const kids = [];
  let folder = null;
  for (const m of list) {
    if (m.folder !== folder) {
      folder = m.folder;
      kids.push(h('div.media-folder', { title: folder }, icon('folder'), h('span', {}, folder.split('/').pop())));
    }
    const toggle = h('button.toggle', {
      title: m.enabled ? 'Leave out of the film' : 'Put back in the film',
      onclick: (e) => { e.stopPropagation(); edit('enable', m.id, { enabled: !m.enabled }, m.enabled ? 'Leaving out' : 'Adding'); },
    }, icon(m.enabled ? 'eyeoff' : 'eye'));
    kids.push(h('div.media-card', {
      'data-id': m.id, title: m.excluded ? `${m.name} — not in the film: ${m.excluded.label}` : m.name,
      onclick: () => selectShot(m.id, { seek: m.enabled }),
    },
    h('img', { src: m.thumb || '', loading: 'lazy', alt: '' }),
    m.enabled ? h('span.badge', {}, `${m.duration.toFixed(1)}s`) : null,
    toggle,
    h('div.meta', {}, m.type === 'video' ? icon('video') : null, h('span.nm', {}, m.name),
      m.type === 'video' ? null : h('span', {}, String(m.score)))));
  }
  if (!list.length) kids.push(h('div.empty.small', { style: 'grid-column:1/-1' }, S.run ? 'Nothing here.' : 'No project open.'));
  grid.replaceChildren(...kids);
  markMedia();
}

function markMedia() {
  for (const c of $$('.media-card')) c.classList.toggle('sel', c.dataset.id === S.selected);
}

// =================================================================== music
async function loadTracks() {
  try { S.tracks = await get('/api/music/tracks'); } catch { S.tracks = []; }
  renderTracks();
  fillNewMusic();
  create.setTracks(S.tracks);
}

function previewButton(url, key) {
  const playing = previewAudio.dataset.key === key && !previewAudio.paused;
  return h('button.icon-btn.pv', {
    title: url ? 'Listen' : 'Generated on first use', disabled: !url,
    onclick: (e) => { e.stopPropagation(); togglePreview(url, key); },
  }, icon(playing ? 'pause' : 'play'));
}

function togglePreview(url, key) {
  if (previewAudio.dataset.key === key && !previewAudio.paused) { previewAudio.pause(); }
  else {
    pause();
    previewAudio.src = url;
    previewAudio.dataset.key = key;
    previewAudio.volume = 0.8;
    previewAudio.play().catch((e) => toast(`Can't play this track: ${e.message}`, 'error'));
  }
  setTimeout(() => { renderTracks(); renderOnline(); }, 50);
}
previewAudio.addEventListener('ended', () => { renderTracks(); renderOnline(); });

function renderTracks() {
  const cur = S.options ? S.options.music_preset : null;
  const look = S.options && lookOf(S.options.look);
  const rows = [
    { key: null, title: 'No music', sub: 'Clip sound only' },
    { key: 'auto', title: 'Auto — match the look', sub: look ? `${look.mood} mood` : '' },
    ...S.tracks.map((t) => ({
      key: t.key, title: t.title, url: t.url,
      sub: [t.mood, t.builtin ? 'built-in' : t.downloaded ? 'downloaded' : 'your file', t.creator].filter(Boolean).join(' · '),
    })),
  ];
  $('#trackList').replaceChildren(...rows.map((r) => h('div.track', {
    class: (cur ?? null) === r.key ? 'on' : '', onclick: () => choosePreset(r.key),
  },
  r.key && r.key !== 'auto' ? previewButton(r.url, r.key) : h('span.icon-btn.pv', {}, icon(r.key ? 'sparkles' : 'x')),
  h('div', {}, h('div.t1', {}, r.title), h('div.t2', {}, r.sub)),
  h('div.right', {}, (cur ?? null) === r.key ? icon('check') : null))));
}

function suggestedTrack(key) {
  if (key === 'auto') {
    const mood = lookOf(S.options.look)?.mood;
    return S.tracks.find((t) => t.builtin && t.mood === mood) || null;
  }
  return S.tracks.find((t) => t.key === key) || null;
}

function choosePreset(key) {
  if (!S.run) { toast('Open or create a project first.'); return; }
  const o = { ...S.options, music_preset: key };
  const t = key ? suggestedTrack(key) : null;
  if (t) Object.assign(o, { music_volume: t.volume, beat_sync: t.beat_sync, music_sync: t.sync });
  S.options = o;
  applyOptions();
  saveOptions();
}

async function importMusic(file) {
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await upload('/api/music/upload', fd);
    await loadTracks();
    toast(`“${r.title}” added to your tracks.`, 'ok');
    choosePreset(r.key);
  } catch (e) { toast(e.message, 'error'); }
}

// ================================================================== online
async function searchOnline(e) {
  e.preventDefault();
  const q = $('#onlineQuery').value.trim();
  const mood = $('#onlineMood').value;
  if (!q && !mood) { toast('Type something to search for, or pick a mood.'); return; }
  $('#onlineResults').replaceChildren(h('div.empty.small', {}, h('div.spinner'), 'Searching…'));
  try {
    S.online = await get(`/api/music/search?${new URLSearchParams({ q, source: $('#onlineSource').value, mood })}`);
  } catch (err) {
    S.online = [];
    $('#onlineResults').replaceChildren(h('div.empty.small', {}, err.message));
    return;
  }
  renderOnline();
}

function renderOnline() {
  if (!S.online.length) {
    if ($('#onlineResults .spinner')) return;
    if (!$('#onlineResults .track')) return;
    $('#onlineResults').replaceChildren(h('div.empty.small', {}, 'No results — try other words or another source.'));
    return;
  }
  $('#onlineResults').replaceChildren(...S.online.map((t, i) => h('div.track', { title: t.attribution },
    previewButton(t.audio_url, `online:${t.source}:${t.id}`),
    h('div', {}, h('div.t1', {}, t.title), h('div.t2', {}, `${t.creator} · ${t.duration ? fmtShort(t.duration) : '?'}`)),
    h('div.right', {},
      h('span.chip.lic', { class: /NC/.test(t.license) ? 'nc' : '', title: t.license_url || '' }, t.license.replace(/^CC /, '')),
      h('button.btn.xs', {
        disabled: !t.downloadable, title: t.downloadable ? 'Download into your tracks' : 'Streaming only: the artist does not allow downloads',
        onclick: (e) => { e.stopPropagation(); useOnline(i); },
      }, 'Use')))));
}

async function useOnline(i) {
  const t = S.online[i];
  try {
    const r = await job(post('/api/music/download', { track: t }), `Downloading “${t.title}”`);
    await loadTracks();
    showTab('left', 'music');
    toast(`Added “${r.title}”. Credit: ${r.attribution}`, 'ok', 7000);
    choosePreset(r.key);
  } catch (e) { toast(e.message, 'error'); }
}

// ================================================================== export
function renderOutputs() {
  const o = S.run ? S.run.outputs : {};
  const items = [];
  for (const [k, label] of [['final', 'Final video'], ['preview', 'Quick preview (15 s)']]) {
    if (!o[k]) continue;
    items.push(h('div.out', {},
      h('div.ic', {}, icon(k === 'final' ? 'film' : 'eye')),
      h('div', {}, h('div.strong', {}, label), h('div.small.muted', {}, o[k].updated.replace('T', ' '))),
      h('button.btn.sm', { onclick: () => openPlayer(o[k].url, `${label} — ${$('#projectName').value}`) }, icon('play'), 'Play')));
  }
  if (!items.length) items.push(h('div.hint', {}, 'Renders appear here. The quick preview takes a few seconds; the final video renders at the resolution above.'));
  $('#outputs').replaceChildren(...items);
}

function openPlayer(url, title) {
  pause();
  $('#playerTitle').textContent = title;
  const v = $('#playerVideo');
  v.src = url;
  $('#player').showModal();
  v.play().catch(() => {});
}

let rendering = false;
async function renderVideo(kind) {
  if (!runId()) { toast('Open or create a project first.'); return; }
  if (rendering) { toast('A render is already running.'); return; }
  rendering = true;
  for (const b of ['#btnPreview', '#btnRender', '#expPreview', '#expRender']) $(b).disabled = true;
  try {
    await queue;   // pending edits first
    const label = kind === 'final' ? 'Rendering the final video' : 'Rendering the preview';
    const r = await job(post(`/api/runs/${runId()}/${kind === 'final' ? 'render' : 'preview'}`), label);
    await refreshRun();
    toast(kind === 'final' ? `Final video ready${r.seconds ? ` in ${Math.round(r.seconds)} s` : ''}.` : 'Preview ready.', 'ok');
    openPlayer(r.url, `${kind === 'final' ? 'Final video' : 'Quick preview'} — ${$('#projectName').value}`);
  } catch (e) { toast(e.message, 'error', 8000); }
  finally {
    rendering = false;
    for (const b of ['#btnPreview', '#btnRender', '#expPreview', '#expRender']) $(b).disabled = false;
  }
}

// ================================================================ projects
async function openHome() {
  $('#home').hidden = false;
  $('#homeClose').hidden = !S.run;
  if (!$('#newFolder').value && S.run) $('#newFolder').value = S.run.source_folder;
  const [projects, recent] = await Promise.all([get('/api/projects').catch(() => []), get('/api/runs').catch(() => [])]);
  $('#projectList').replaceChildren(...(projects.length ? projects.map((p) => h('div.home-item', {
    title: p.path, onclick: () => openProject(p.path),
  }, h('div.t1', {}, p.name), h('div.t2', {}, p.folder), h('div.t3', {}, `${p.shots} shots`, h('br'), (p.saved_at || '').slice(0, 16).replace('T', ' '))))
    : [h('div.empty.small', {}, 'No saved projects yet. Use Save (Ctrl+S) in the editor.')]));
  $('#recentList').replaceChildren(...(recent.length ? recent.map((r) => h('div.home-item', {
    title: r.folder, onclick: () => loadRun(r.run_id).catch((e) => toast(e.message, 'error')),
  }, h('div.t1', {}, r.folder_name || r.run_id), h('div.t2', {}, `${lookOf(r.look)?.label || r.look} · ${r.run_id}${r.folder_exists ? '' : ' · folder missing'}`),
    h('div.t3', {}, `${r.shots} shots · ${fmtShort(r.duration)}`, h('br'), r.updated.replace('T', ' '))))
    : [h('div.empty.small', {}, 'No sessions yet.')]));
}

function closeHome() { $('#home').hidden = true; }

function fillNewMusic() {
  const sel = $('#newMusic');
  const cur = sel.value || 'auto';
  sel.replaceChildren(h('option', { value: '' }, 'No music'), h('option', { value: 'auto' }, 'Auto — match the look'),
    ...S.tracks.map((t) => h('option', { value: t.key }, `${t.title} · ${t.mood}`)));
  sel.value = cur;
}

async function createProject() {
  const folder = $('#newFolder').value.trim();
  if (!folder) { toast('Choose the media folder first.'); $('#newFolder').focus(); return; }
  const look = $('#newLook').value;
  const preset = $('#newMusic').value || null;
  const options = { ...S.catalog.default_options, look, music_preset: preset };
  S.options = options;   // so suggestedTrack('auto') sees the chosen look
  const t = preset ? suggestedTrack(preset) : null;
  if (t) Object.assign(options, { music_volume: t.volume, beat_sync: t.beat_sync, music_sync: t.sync });
  const btn = $('#newCreate');
  btn.disabled = true;
  $('#newProgress').hidden = false;
  try {
    const id = await job(post('/api/runs', {
      folder, target_duration: parseFloat($('#newDuration').value) || S.catalog.default_target_duration,
      sort_mode: $('#newSort .on')?.dataset.v || 'folder', options,
    }), 'Generating the plan', {
      onProgress: (j) => { $('#newBar').style.width = `${Math.round(j.progress * 100)}%`; $('#newMsg').textContent = j.message; },
    });
    await loadRun(id, { name: folder.split(/[\\/]/).filter(Boolean).pop() });
    loadTracks();
    toast('Plan generated. Fine-tune it here, then Render.', 'ok');
  } catch (e) { toast(e.message, 'error', 8000); }
  finally { btn.disabled = false; $('#newProgress').hidden = true; $('#newBar').style.width = '0'; }
}

async function openProject(path) {
  try {
    const r = await job(post('/api/projects/open', { path }), 'Opening the project', { stage: true });
    await loadRun(r.run_id, { name: r.name });
    if (r.missing && r.missing.length) toast(`${r.missing.length} file(s) missing and left out: ${r.missing.slice(0, 4).join(', ')}`, 'error', 9000);
    else toast(`Opened “${r.name}”.`, 'ok');
  } catch (e) { toast(e.message, 'error'); }
}

async function saveProject() {
  if (!runId()) { toast('Nothing to save yet.'); return; }
  await queue;
  const name = $('#projectName').value.trim() || 'Untitled';
  try {
    const r = await post('/api/projects', { run_id: runId(), name });
    localStorage.setItem(`ovs.name.${runId()}`, name);
    toast(`Saved “${r.name}”.`, 'ok');
  } catch (e) { toast(e.message, 'error'); }
}

// ================================================================== wiring
function bindUi() {
  $('#btnHome').addEventListener('click', openHome);
  $('#homeClose').addEventListener('click', closeHome);
  $('#btnSave').addEventListener('click', saveProject);
  $('#btnPreview').addEventListener('click', () => renderVideo('preview'));
  $('#btnRender').addEventListener('click', () => renderVideo('final'));
  $('#expPreview').addEventListener('click', () => renderVideo('preview'));
  $('#expRender').addEventListener('click', () => renderVideo('final'));
  $('#btnOpenFolder').addEventListener('click', () => runId() && post(`/api/runs/${runId()}/open-folder`).catch((e) => toast(e.message, 'error')));
  $('#projectName').addEventListener('change', (e) => runId() && localStorage.setItem(`ovs.name.${runId()}`, e.target.value));
  $('#projectName').addEventListener('keydown', (e) => { if (e.key === 'Enter') e.target.blur(); });

  $('#tPlay').addEventListener('click', () => (S.playing ? pause() : play()));
  $('#tBack').addEventListener('click', () => { pause(); seek(S.playhead - 1); });
  $('#tFwd').addEventListener('click', () => { pause(); seek(S.playhead + 1); });
  $('#tPrev').addEventListener('click', () => { pause(); stepCut(-1); });
  $('#tNext').addEventListener('click', () => { pause(); stepCut(1); });
  $('#closeVideo').addEventListener('click', hideVideo);
  $('#monVideo').addEventListener('ended', () => setTimeout(hideVideo, 600));

  $('#mediaFilter').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    S.mediaFilter = b.dataset.v;
    for (const x of $$('#mediaFilter button')) x.classList.toggle('on', x === b);
    renderMedia();
  });

  $('#btnImportMusic').addEventListener('click', () => $('#musicFile').click());
  $('#musicFile').addEventListener('change', (e) => { const f = e.target.files[0]; e.target.value = ''; if (f) importMusic(f); });
  $('#onlineForm').addEventListener('submit', searchOnline);

  $('#newBrowse').addEventListener('click', async () => {
    const r = await post('/api/dialog/folder').catch(() => ({ path: '' }));
    if (r.path) $('#newFolder').value = r.path;
  });
  $('#newSort').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (b) for (const x of $$('#newSort button')) x.classList.toggle('on', x === b);
  });
  $('#newCreate').addEventListener('click', createProject);
  $('#homeToCreate').addEventListener('click', () => setMode('create'));
  $('#newFolder').addEventListener('keydown', (e) => { if (e.key === 'Enter') createProject(); });
  $('#openFile').addEventListener('click', async () => {
    const r = await post('/api/dialog/project').catch(() => ({ path: '' }));
    if (r.path) openProject(r.path);
  });

  $('#playerClose').addEventListener('click', () => $('#player').close());
  $('#player').addEventListener('close', () => $('#playerVideo').pause());

  document.addEventListener('keyup', (e) => {
    if (e.key === ' ' && e.target.tagName === 'BUTTON' && !isTyping(e)) e.preventDefault();
  });
  $('#modeSwitch').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (b && b.dataset.mode !== mode()) setMode(b.dataset.mode);
  });

  document.addEventListener('keydown', (e) => {
    if (mode() === 'create') return;   // editing shortcuts belong to the Remix workspace
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); saveProject(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'o') { e.preventDefault(); openHome(); return; }
    if (e.key === 'Escape' && !$('#home').hidden && S.run) { closeHome(); return; }
    if (isTyping(e) || !$('#home').hidden || $('#player').open) return;
    const inTimeline = e.target.closest && e.target.closest('.ovs-tl-root');
    if (e.key === ' ') {
      e.preventDefault();
      if (e.target.tagName === 'BUTTON') e.target.blur();   // Space plays, it doesn't click the focused button
      S.playing ? pause() : play();
    }
    else if (e.key === ',') stepCut(-1);
    else if (e.key === '.') stepCut(1);
    else if (!inTimeline && e.key === 'ArrowLeft') { pause(); seek(S.playhead - (e.shiftKey ? 5 : 1)); }
    else if (!inTimeline && e.key === 'ArrowRight') { pause(); seek(S.playhead + (e.shiftKey ? 5 : 1)); }
  });
}

async function initTimeline() {
  TL = await mountTimeline($('#timeline'), {
    select: (d) => {
      pause();
      if (d.kind === 'transition') {
        const tr = S.view && S.view.transitions[d.index];
        if (!tr) return;
        selectShot(tr.into, { seek: false }).then(() => { seek(tr.start + tr.duration / 2); $('#shotTransition').focus(); });
      } else if (d.id) selectShot(d.id);
    },
    release: (d) => { pause(); seek(Number(d.t) || 0); },
    apply: (d) => {
      const map = { move: { before: d.before }, duration: { duration: d.duration }, caption: { text: d.text }, toggle: {} };
      if (!(d.action in map)) return;
      edit(d.action, d.shot, map[d.action], d.action === 'move' ? 'Moving' : 'Updating');
    },
  });
  TL.set(null);
}

async function init() {
  hydrateIcons();
  initTabs();
  S.catalog = await get('/api/catalog');
  fillChoices();
  hydrateIcons();
  bindOptions();
  bindInspector();
  bindUi();
  applyOptions();
  await initTimeline();
  await create.initCreate({ job, setSummary: (text) => { $('#stSummary').textContent = text; } });
  hydrateIcons();
  await loadTracks();
  get('/api/system').then((s) => { $('#stRight').textContent = `${s.disk_free_gb} GB free`; }).catch(() => {});
  const last = localStorage.getItem('ovs.run');
  if (last) {
    try { await loadRun(last); } catch { localStorage.removeItem('ovs.run'); }
  }
  await setMode(localStorage.getItem('ovs.mode') === 'create' ? 'create' : 'remix');
}

init().catch((e) => { console.error(e); toast(`Could not start: ${e.message}`, 'error', 15000); });
