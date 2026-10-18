// Create → Voice: the narration engine (Edge TTS online, Kokoro or
// Chatterbox local), language and voice, with previews, installing the
// local engines and voice samples for Chatterbox. The choice is used for
// new videos; "Use for this video" applies it to the open one.
import { $, h, icon, toast } from './dom.js';
import { get, post, put, upload } from './api.js';

const V = { cat: null, ctx: null, sel: { engine: 'edge_tts', language: 'en', voice: null }, run: null, onRun: null };
const audio = new Audio();

export async function initVoice(ctx, { onRun } = {}) {
  V.ctx = ctx;
  V.onRun = onRun;
  try { Object.assign(V.sel, JSON.parse(localStorage.getItem('ovs.voice') || '{}')); } catch { /* fresh */ }
  await refresh();
  $('#vLanguage').addEventListener('change', (e) => { V.sel.language = e.target.value; V.sel.voice = null; fix(); render(); });
  $('#vVoice').addEventListener('change', (e) => { V.sel.voice = e.target.value; save(); renderRun(); });
  $('#vPreview').addEventListener('click', preview);
  $('#vSampleBtn').addEventListener('click', () => $('#vSampleFile').click());
  $('#vSampleFile').addEventListener('change', (e) => { const f = e.target.files[0]; e.target.value = ''; if (f) addSample(f); });
  $('#vApply').addEventListener('click', applyToRun);
  $('#cVoiceLine').addEventListener('click', () => ctx.showTab('cright', 'voice'));
}

async function refresh() {
  V.cat = await get('/api/voices');
  fix();
  render();
}

const engine = (key = V.sel.engine) => V.cat.engines.find((e) => e.value === key);
const voicesOf = (key, lang) => (engine(key)?.voices || {})[lang] || [];
const langLabel = (code) => V.cat.languages.find((l) => l.value === code)?.label || code;

/** Keeps the selection valid: language offered by the engine, voice of that language. */
function fix() {
  if (!V.cat.languages.some((l) => l.value === V.sel.language)) V.sel.language = 'en';
  if (!voicesOf(V.sel.engine, V.sel.language).length) V.sel.engine = 'edge_tts';   // Edge speaks them all
  const list = voicesOf(V.sel.engine, V.sel.language);
  if (!list.some((v) => v.value === V.sel.voice)) V.sel.voice = list[0]?.value || null;
  save();
}

function save() {
  try { localStorage.setItem('ovs.voice', JSON.stringify(V.sel)); } catch { /* private mode */ }
  renderLine();
}

/** What a new video is created with. */
export function choice() {
  return { language: V.sel.language, tts_engine: V.sel.engine, tts_voice: V.sel.voice };
}

function render() {
  $('#vLanguage').replaceChildren(...V.cat.languages.map((l) => h('option', { value: l.value }, l.label)));
  $('#vLanguage').value = V.sel.language;
  $('#vEngines').replaceChildren(...V.cat.engines.map((e) => {
    const langs = Object.keys(e.voices);
    const offers = langs.includes(V.sel.language);
    const card = h('div.engine', {
      class: `${e.value === V.sel.engine ? 'on' : ''} ${offers ? '' : 'na'}`,
      title: offers ? '' : `${e.label} has no ${langLabel(V.sel.language)} voices`,
      onclick: () => {
        if (!offers) { toast(`${e.label} doesn't speak ${langLabel(V.sel.language)}.`); return; }
        V.sel.engine = e.value; V.sel.voice = null; fix(); render();
      },
    },
    h('div.row.between', {}, h('span.strong', {}, e.label),
      h('span.chip', { class: e.kind === 'online' ? 'ghost' : 'accent' }, e.kind)),
    h('div.small.muted', {}, e.hint),
    h('div.row.between.small', {},
      h('span.muted', {}, `${e.licence} · ${langs.map((l) => l.toUpperCase()).join(' ')}`),
      e.installed ? h('span.ok', {}, e.value === 'edge_tts' ? 'Ready' : 'Installed')
        : h('button.btn.xs', { onclick: (ev) => { ev.stopPropagation(); install(e); } },
          icon('export'), `Install${e.size ? ` (${e.size})` : ''}`)));
    return card;
  }));
  const e = engine();
  const list = voicesOf(V.sel.engine, V.sel.language);
  $('#vVoice').replaceChildren(...list.map((v) => h('option', { value: v.value }, v.label)));
  $('#vVoice').value = V.sel.voice || '';
  const ready = e && e.installed;
  $('#vPreview').disabled = !ready || !list.length;
  $('#vSample').hidden = V.sel.engine !== 'chatterbox';
  $('#vNote').textContent = !ready ? `${e.label} isn't installed yet — click Install on its card.`
    : e.value === 'edge_tts' ? 'Online: the narration text is sent to Microsoft.'
      : e.value === 'chatterbox' && !V.cat.gpu ? 'No NVIDIA GPU found: Chatterbox will be very slow on the CPU.'
        : 'Runs on this computer. The first use downloads the model.';
  renderRun();
  renderLine();
}

function renderLine() {
  if (!V.cat) return;
  const v = voicesOf(V.sel.engine, V.sel.language).find((x) => x.value === V.sel.voice);
  $('#cVoiceLine').replaceChildren(icon('volume'),
    h('span.ellipsis', {}, `${engine()?.label || ''} · ${langLabel(V.sel.language)} · ${v ? v.label : '—'}`),
    h('span.link', {}, 'Change'));
}

/** The open video's voice, and whether the selection can be applied to it. */
export function setRun(run) {
  V.run = run;
  if (V.cat) renderRun();
}

function renderRun() {
  const r = V.run;
  const box = $('#vRun');
  box.hidden = !r;
  if (!r || !V.cat) return;
  const cur = voicesOf(r.tts_engine, r.language).find((x) => x.value === r.tts_voice);
  const curLabel = `${engine(r.tts_engine)?.label || r.tts_engine} · ${langLabel(r.language)}${cur ? ` · ${cur.label}` : ''}`;
  $('#vRunNow').textContent = curLabel;
  const same = r.tts_engine === V.sel.engine && (r.tts_voice || null) === (V.sel.voice || null);
  const sameLang = r.language === V.sel.language;
  const btn = $('#vApply');
  btn.disabled = same || !sameLang || !engine()?.installed;
  btn.title = !sameLang ? `This video's script is in ${langLabel(r.language)}: pick a voice in ${langLabel(r.language)}`
    : same ? 'Already the voice of this video' : 'The narration is redone on the next Generate';
}

async function applyToRun() {
  if (!V.run) return;
  try {
    const st = await put(`/api/create/${V.run.run_id}/voice`, { engine: V.sel.engine, voice: V.sel.voice });
    V.run = st;
    renderRun();
    V.onRun?.(st);
    toast(st.final ? 'Voice changed — click Generate to redo the narration.' : 'Voice set for this video.', 'ok');
  } catch (e) { toast(e.message, 'error'); }
}

async function preview() {
  const btn = $('#vPreview');
  if (!audio.paused) { audio.pause(); return; }
  btn.disabled = true;
  try {
    const r = await V.ctx.job(post('/api/voices/preview', { engine: V.sel.engine, language: V.sel.language, voice: V.sel.voice }),
      `Preview · ${engine().label}`);
    audio.src = r.url;
    await audio.play();
  } catch (e) { toast(e.message, 'error', 9000); }
  finally { btn.disabled = false; }
}

async function install(e) {
  if (!confirm(`Install ${e.label}?\n\nIt downloads ${e.size || 'a few GB'} into studio/voices (PyTorch and the engine); `
    + 'the model itself downloads the first time you use it.')) return;
  try {
    V.cat = await V.ctx.job(post('/api/voices/install', { engine: e.value }), `Installing ${e.label}`);
    V.sel.engine = e.value; V.sel.voice = null; fix(); render();
    toast(`${e.label} installed. Try Preview.`, 'ok');
  } catch (err) { toast(err.message, 'error', 12000); }
}

async function addSample(file) {
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await upload('/api/voices/samples', fd);
    V.cat = r.catalog;
    V.sel.voice = r.voice;
    fix(); render();
    toast('Voice sample added — Preview to hear it.', 'ok');
  } catch (e) { toast(e.message, 'error'); }
}
