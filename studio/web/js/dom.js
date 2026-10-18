// Small DOM helpers, icons, toasts and formatting.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/** h('div.card', {title: 'x', onclick}, child, 'text') */
export function h(tag, attrs = {}, ...kids) {
  const [name, ...classes] = tag.split('.');
  const el = document.createElement(name || 'div');
  if (classes.length) el.className = classes.join(' ');
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className += (el.className ? ' ' : '') + v;
    else if (k === 'text') el.textContent = v;
    else if (k in el && typeof v !== 'string') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

const P = (d) => `<path d="${d}"/>`;
const ICONS = {
  logo: '<rect x="1" y="1" width="22" height="22" rx="6" fill="#6f7bd4" stroke="none"/><path d="M9.5 7.5l7 4.5-7 4.5z" fill="#fff" stroke="none"/>',
  folder: P('M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'),
  save: P('M5 3h11l3 3v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z') + P('M8 3v5h7V3M7 21v-7h10v7'),
  eye: P('M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z') + '<circle cx="12" cy="12" r="3"/>',
  eyeoff: P('M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 3.9M6.6 6.6C3.9 8.4 2 12 2 12s3.6 7 10 7c1.6 0 3-.4 4.3-1M9.9 9.9a3 3 0 0 0 4.2 4.2'),
  export: P('M12 3v12M7 10l5 5 5-5M5 21h14'),
  upload: P('M12 16V4M7 9l5-5 5 5M5 20h14'),
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/>' + P('M21 16l-5-5-9 9'),
  music: P('M9 18V5l11-2v13') + '<circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
  globe: '<circle cx="12" cy="12" r="9"/>' + P('M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18'),
  volume: P('M4 9h4l5-4v14l-5-4H4zM16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11'),
  search: '<circle cx="11" cy="11" r="7"/>' + P('M20 20l-4-4'),
  film: '<rect x="3" y="4" width="18" height="16" rx="2"/>' + P('M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4'),
  x: P('M6 6l12 12M18 6L6 18'),
  prev: P('M18 6v12l-9-6zM6 6v12'),
  next: P('M6 6v12l9-6zM18 6v12'),
  back: P('M11 7l-5 5 5 5M18 7l-5 5 5 5'),
  fwd: P('M13 7l5 5-5 5M6 7l5 5-5 5'),
  play: '<path d="M7 4.5v15l13-7.5z" fill="currentColor" stroke="none"/>',
  pause: '<path d="M6.5 4h4v16h-4zM13.5 4h4v16h-4z" fill="currentColor" stroke="none"/>',
  crop: P('M6 2v14a2 2 0 0 0 2 2h14M2 6h14a2 2 0 0 1 2 2v14'),
  palette: P('M12 3a9 9 0 1 0 0 18c1.1 0 1.6-.8 1.6-1.6 0-1.3-1-1.4-1-2.6 0-.9.7-1.6 1.6-1.6H16a5 5 0 0 0 5-5c0-4-4-7.2-9-7.2z') + '<circle cx="7.5" cy="11" r="1"/><circle cx="9.5" cy="7" r="1"/><circle cx="14.5" cy="6.8" r="1"/>',
  text: P('M5 6V4h14v2M12 4v16M9 20h6'),
  shuffle: P('M16 3h5v5M4 20L21 3M21 16v5h-5M15 15l6 6M4 4l5 5'),
  left: P('M15 6l-6 6 6 6'),
  right: P('M9 6l6 6-6 6'),
  scissors: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/>' + P('M20 4L8.1 15.9M14.5 14.5L20 20M8.1 8.1L12 12'),
  sparkles: P('M12 3l1.8 4.7 4.7 1.8-4.7 1.8L12 16l-1.8-4.7-4.7-1.8 4.7-1.8zM19 15l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z'),
  check: P('M5 12l5 5 9-10'),
  video: '<rect x="3" y="6" width="13" height="12" rx="2"/>' + P('M16 10l5-3v10l-5-3'),
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/>' + P('M8 11V7a4 4 0 0 1 8 0v4'),
};

export function icon(name) {
  const t = document.createElement('template');
  t.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;
  return t.content.firstChild;
}

export function hydrateIcons(root = document) {
  for (const el of $$('[data-icon]', root)) {
    if (el.dataset.iconDone) continue;
    el.prepend(icon(el.dataset.icon));
    el.dataset.iconDone = '1';
  }
}

export function toast(msg, kind = 'info', ms = 4200) {
  const el = h('div.toast', { class: kind }, msg);
  $('#toasts').append(el);
  setTimeout(() => el.remove(), ms);
}

export function fmt(t) {
  t = Math.max(0, Number(t) || 0);
  const m = Math.floor(t / 60);
  return `${String(m).padStart(2, '0')}:${(t - m * 60).toFixed(2).padStart(5, '0')}`;
}

export function fmtShort(t) {
  t = Math.round(Math.max(0, Number(t) || 0));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`;
}

export function debounce(fn, ms) {
  let id;
  return (...args) => { clearTimeout(id); id = setTimeout(() => fn(...args), ms); };
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function isTyping(e) {
  const t = e.target;
  return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
}
