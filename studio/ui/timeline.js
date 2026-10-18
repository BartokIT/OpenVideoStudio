// OpenVideoStudio timeline. Hosted by web/js/timeline-host.js, which runs
// this file with: element, trigger, props, server, upload, watch.
// props.value is the JSON produced by core/pro/preview.timeline_view().
// Events sent to Python:
//   trigger('select',  {kind: 'shot', id})   | {kind: 'transition', index}
//   trigger('release', {t})                   playhead moved
//   trigger('apply',   {action: 'move', shot, before}) | {action: 'duration', shot, duration}
//                      | {action: 'caption', shot, text} | {action: 'toggle', shot}
(function () {
  const BASE_PPS = 14;           // pixels per second at zoom 1
  const H = { ruler: 26, v: 64, t: 28, a: 46 };
  const S = { zoom: 1, scrollLeft: 0, snap: null, lastKey: null, playhead: 0, selected: null, selTr: null, drag: null };

  const fmt = (t) => {
    t = Math.max(0, t || 0);
    const m = Math.floor(t / 60), s = t - m * 60;
    return String(m).padStart(2, '0') + ':' + s.toFixed(2).padStart(5, '0');
  };
  const pps = () => BASE_PPS * S.zoom;
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function data() {
    let v = props.value;
    if (typeof v === 'string') { try { v = JSON.parse(v); } catch (e) { v = null; } }
    return v && v.shots ? v : null;
  }
  function root() {
    let r = element.querySelector('.ovs-tl-root');
    if (!r) { r = document.createElement('div'); r.className = 'ovs-tl-root'; element.appendChild(r); }
    r.tabIndex = 0;
    return r;
  }

  // ------------------------------------------------------------ rendering
  function render() {
    const d = data(), r = root();
    if (!d || !d.shots.length) {
      r.innerHTML = '<div class="ovs-tl-empty">Generate a plan to see the timeline.</div>';
      S.lastKey = null;
      return;
    }
    if (S.snap === null) S.snap = !!d.snap;
    const key = JSON.stringify(Object.assign({}, d, { playhead: 0, selected: null }));
    S.playhead = d.playhead || 0;
    S.selected = d.selected || null;
    if (key === S.lastKey && r.querySelector('.ovs-tl-canvas')) { light(d); return; }
    S.lastKey = key;
    build(d, r);
  }

  function light(d) {
    const r = root();
    r.querySelectorAll('.ovs-clip').forEach((c) => c.classList.toggle('selected', c.dataset.id === S.selected));
    r.querySelectorAll('.ovs-tr').forEach((c) => c.classList.toggle('selected', +c.dataset.index === S.selTr));
    setPlayhead(S.playhead, true);
  }

  function setPlayhead(t, scrollTo) {
    const r = root(), d = data();
    if (!d) return;
    t = Math.max(0, Math.min(t, d.total));
    S.playhead = t;
    const ph = r.querySelector('.ovs-ph');
    if (ph) ph.style.left = (t * pps()) + 'px';
    const ro = r.querySelector('.ovs-tl-time');
    if (ro) ro.textContent = fmt(t) + ' / ' + fmt(d.total);
    if (scrollTo) {
      const sc = r.querySelector('.ovs-tl-scroll');
      const x = t * pps();
      if (sc && (x < sc.scrollLeft + 10 || x > sc.scrollLeft + sc.clientWidth - 10)) {
        sc.scrollLeft = Math.max(0, x - sc.clientWidth / 3);
      }
    }
  }

  function build(d, r) {
    r.innerHTML = '';
    const bar = document.createElement('div');
    bar.className = 'ovs-tl-bar';
    bar.innerHTML =
      '<label>Zoom <input type="range" class="ovs-zoom" min="0.2" max="8" step="0.05" value="' + S.zoom + '"></label>' +
      '<button class="ovs-fit" type="button">Fit</button>' +
      '<label><input type="checkbox" class="ovs-snap"' + (S.snap ? ' checked' : '') + (d.audio ? '' : ' disabled') + '> Snap to beats</label>' +
      '<span class="ovs-tl-hint">drag a clip to reorder · drag its right edge for duration · double-click a text to edit · Del removes from the cut</span>' +
      '<span class="ovs-tl-time"></span>';
    r.appendChild(bar);

    const body = document.createElement('div');
    body.className = 'ovs-tl-body';
    const gutter = document.createElement('div');
    gutter.className = 'ovs-tl-gutter';
    gutter.innerHTML = '<div style="--h:' + H.ruler + 'px"></div><div style="--h:' + H.v + 'px">V1</div>' +
      '<div style="--h:' + H.t + 'px">T1</div><div style="--h:' + H.a + 'px">A1</div>';
    body.appendChild(gutter);
    const scroll = document.createElement('div');
    scroll.className = 'ovs-tl-scroll';
    const canvas = document.createElement('div');
    canvas.className = 'ovs-tl-canvas';
    const W = Math.ceil(d.total * pps()) + 60;
    canvas.style.width = W + 'px';
    scroll.appendChild(canvas);
    body.appendChild(scroll);
    r.appendChild(body);

    canvas.appendChild(buildRuler(d, W));
    canvas.appendChild(buildVideo(d));
    canvas.appendChild(buildText(d));
    canvas.appendChild(buildAudio(d, W));
    const ph = document.createElement('div');
    ph.className = 'ovs-ph';
    canvas.appendChild(ph);

    scroll.scrollLeft = S.scrollLeft;
    scroll.addEventListener('scroll', () => { S.scrollLeft = scroll.scrollLeft; });
    bar.querySelector('.ovs-zoom').addEventListener('input', (e) => {
      const nz = +e.target.value, sc = r.querySelector('.ovs-tl-scroll');
      const centre = (sc.scrollLeft + sc.clientWidth / 2) / pps();
      S.zoom = nz;
      S.scrollLeft = Math.max(0, centre * pps() - sc.clientWidth / 2);
      S.lastKey = null; render();
    });
    bar.querySelector('.ovs-fit').addEventListener('click', () => {
      const sc = r.querySelector('.ovs-tl-scroll');
      S.zoom = Math.max(0.2, Math.min(8, (sc.clientWidth - 70) / d.total / BASE_PPS));
      S.scrollLeft = 0; S.lastKey = null; render();
    });
    bar.querySelector('.ovs-snap').addEventListener('change', (e) => { S.snap = e.target.checked; });

    wire(d, r, scroll, canvas);
    light(d);
  }

  function buildRuler(d, W) {
    const t = document.createElement('div');
    t.className = 'ovs-track ovs-ruler';
    t.style.height = H.ruler + 'px';
    const p = pps();
    const step = p >= 60 ? 1 : p >= 25 ? 2 : p >= 12 ? 5 : p >= 5 ? 10 : 30;
    for (let s = 0; s <= d.total + 1e-6; s += step) {
      const k = document.createElement('div');
      const major = (s / step) % (step === 1 ? 5 : step === 2 ? 5 : 2) === 0;
      k.className = 'tick' + (major ? ' major' : '');
      k.style.left = (s * p) + 'px';
      if (major) k.innerHTML = '<span>' + fmt(s).replace(/\.\d+$/, '') + '</span>';
      t.appendChild(k);
    }
    (d.chapters || []).forEach((c, i) => {
      const e = document.createElement('div');
      e.className = 'ovs-chap ' + (i % 2 ? 'b' : 'a');
      e.style.left = (c.start * p) + 'px';
      e.style.width = Math.max(2, (c.end - c.start) * p - 1) + 'px';
      e.textContent = c.name;
      e.title = c.name;
      t.appendChild(e);
    });
    return t;
  }

  function buildVideo(d) {
    const t = document.createElement('div');
    t.className = 'ovs-track ovs-video';
    t.style.height = H.v + 'px';
    const p = pps();
    d.shots.forEach((s) => {
      const c = document.createElement('div');
      c.className = 'ovs-clip ' + s.type;
      c.dataset.id = s.id;
      c.style.left = (s.start * p) + 'px';
      c.style.width = Math.max(6, (s.end - s.start) * p - 2) + 'px';
      if (s.thumb) c.style.backgroundImage = 'url("' + s.thumb + '")';
      c.title = s.name + ' · ' + s.duration.toFixed(1) + ' s' + (s.motion ? ' · ' + s.motion : '') + (s.caption ? ' · “' + s.caption + '”' : '');
      c.innerHTML = '<span class="ty">' + (s.type === 'video' ? '▶' : (s.index + 1)) + '</span>' +
        '<span class="du">' + s.duration.toFixed(1) + 's</span>' +
        '<span class="nm">' + esc(s.name) + '</span><div class="ovs-handle"></div>';
      t.appendChild(c);
    });
    (d.transitions || []).forEach((tr) => {
      const e = document.createElement('div');
      e.className = 'ovs-tr' + (tr.override ? ' override' : '') + (tr.type === 'morph' ? ' morph' : '');
      e.dataset.index = tr.index;
      e.style.left = (tr.start * p) + 'px';
      e.style.width = Math.max(14, (tr.end - tr.start) * p) + 'px';
      e.textContent = tr.label;
      e.title = tr.label + ' · ' + tr.duration.toFixed(2) + ' s' + (tr.override ? ' · chosen by you' : ' · auto');
      t.appendChild(e);
    });
    if (d.fade_in > 0) {
      const f = document.createElement('div'); f.className = 'ovs-fade';
      f.style.left = '0px'; f.style.width = (d.fade_in * p) + 'px'; t.appendChild(f);
    }
    if (d.fade_out > 0) {
      const f = document.createElement('div'); f.className = 'ovs-fade';
      f.style.left = ((d.total - d.fade_out) * p) + 'px'; f.style.width = (d.fade_out * p) + 'px'; t.appendChild(f);
    }
    return t;
  }

  function buildText(d) {
    const t = document.createElement('div');
    t.className = 'ovs-track ovs-text';
    t.style.height = H.t + 'px';
    const p = pps();
    (d.texts || []).forEach((x) => {
      const e = document.createElement('div');
      e.className = 'ovs-txt ' + x.kind + (x.editable ? ' editable' : '');
      e.dataset.shot = x.shot;
      e.dataset.kind = x.kind;
      e.dataset.edit = x.edit_text != null ? x.edit_text : x.text;
      e.style.left = (x.start * p) + 'px';
      e.style.width = Math.max(18, (x.end - x.start) * p - 2) + 'px';
      e.textContent = x.text;
      e.title = x.kind + ': ' + x.text + (x.editable ? ' (double-click to edit)' : ' (edit in Titles & captions)');
      t.appendChild(e);
    });
    return t;
  }

  function buildAudio(d, W) {
    const t = document.createElement('div');
    t.className = 'ovs-track ovs-audio';
    t.style.height = H.a + 'px';
    if (!d.audio) {
      t.innerHTML = '<div class="ovs-noaudio">No music — pick a preset or a file under Music.</div>';
      return t;
    }
    const cv = document.createElement('canvas');
    cv.width = W; cv.height = H.a;
    const ctx = cv.getContext('2d');
    const p = pps(), a = d.audio, peaks = a.peaks || [], dt = a.peak_seconds || 0.1;
    ctx.fillStyle = '#7c8299';
    const mid = H.a / 2;
    for (let i = 0; i < peaks.length; i++) {
      const x = i * dt * p;
      if (x > d.total * p) break;
      const h = Math.max(1, peaks[i] * (H.a - 6));
      ctx.fillRect(x, mid - h / 2, Math.max(1, dt * p - 0.5), h);
    }
    // beats: short ticks · bars (downbeats): full height · accents: dots on top
    ctx.fillStyle = 'rgba(224,166,64,.55)';
    looped(a.beats, a.duration, d.total).forEach((b) => ctx.fillRect(b * p, H.a - 9, 1, 9));
    ctx.fillStyle = '#e0a640';
    looped(a.downbeats, a.duration, d.total).forEach((b) => ctx.fillRect(b * p, 0, 1.5, H.a));
    ctx.fillStyle = '#ff6b6b';
    looped(a.accents, a.duration, d.total).forEach((b) => {
      ctx.beginPath(); ctx.arc(b * p, 4, 2.5, 0, Math.PI * 2); ctx.fill();
    });
    if (a.duration && a.duration < d.total) {           // the file loops: mark the loop points
      ctx.fillStyle = '#ff8f66';
      for (let x = a.duration; x < d.total; x += a.duration) ctx.fillRect(x * p - 1, 0, 2, H.a);
    }
    t.appendChild(cv);
    const nm = document.createElement('div');
    nm.className = 'nm';
    const bits = ['♪ ' + a.name];
    if (a.tempo) bits.push(Math.round(a.tempo) + ' BPM');
    if (a.meter) bits.push(a.meter + '/4');
    if (d.music_sync) bits.push('cuts: ' + ({ bars: 'on the bars', beats: 'on every beat', accents: 'on the accents',
      follow: 'follow the music', nudge: 'light nudge' }[d.music_sync] || d.music_sync));
    nm.textContent = bits.join(' · ');
    t.appendChild(nm);
    return t;
  }

  // event times of the music file, repeated when the mix loops it
  function looped(times, period, until) {
    const out = [];
    if (!times || !times.length) return out;
    if (!period || period <= 0) return times.filter((x) => x <= until);
    for (let k = 0; k * period <= until; k++) {
      for (const x of times) { const v = x + k * period; if (v > until) break; out.push(v); }
    }
    return out;
  }

  // ---------------------------------------------------------- interaction
  function wire(d, r, scroll, canvas) {
    const p = pps();
    const xOf = (ev) => ev.clientX - canvas.getBoundingClientRect().left;
    const a = d.audio || {};
    const grid = looped((d.music_sync === 'bars' && a.downbeats && a.downbeats.length) ? a.downbeats : a.beats,
      a.duration, d.total + 30);
    const reach = d.music_sync === 'bars' && a.tempo ? Math.max(0.6, 2 * 60 / a.tempo) : 0.6;
    const snapT = (t) => {
      if (!S.snap || !grid.length) return t;
      let best = null;
      for (const b of grid) { if (best === null || Math.abs(b - t) < Math.abs(best - t)) best = b; }
      return best !== null && Math.abs(best - t) <= reach ? best : t;
    };

    canvas.addEventListener('pointerdown', (ev) => {
      if (ev.button !== 0) return;
      const handle = ev.target.closest('.ovs-handle');
      const clip = ev.target.closest('.ovs-clip');
      const tr = ev.target.closest('.ovs-tr');
      const txt = ev.target.closest('.ovs-txt');
      if (tr) {
        S.selTr = +tr.dataset.index; S.selected = null; light(d);
        trigger('select', { kind: 'transition', index: +tr.dataset.index });
        ev.preventDefault(); return;
      }
      if (txt) { ev.preventDefault(); return; }
      if (handle && clip) {
        const s = d.shots.find((x) => x.id === clip.dataset.id);
        S.drag = { mode: 'resize', clip, shot: s, x0: xOf(ev), dur: s.duration };
        clip.setPointerCapture && canvas.setPointerCapture(ev.pointerId);
        ev.preventDefault(); return;
      }
      if (clip) {
        const s = d.shots.find((x) => x.id === clip.dataset.id);
        S.drag = { mode: 'maybe', clip, shot: s, x0: xOf(ev), moved: false };
        canvas.setPointerCapture(ev.pointerId);
        ev.preventDefault(); return;
      }
      // ruler / empty space: scrub
      S.drag = { mode: 'scrub' };
      canvas.setPointerCapture(ev.pointerId);
      setPlayhead(xOf(ev) / p, false);
      ev.preventDefault();
    });

    canvas.addEventListener('pointermove', (ev) => {
      const g = S.drag;
      if (!g) return;
      const x = xOf(ev);
      if (g.mode === 'scrub') { setPlayhead(x / p, false); return; }
      if (g.mode === 'resize') {
        let dur = Math.max(0.5, g.shot.duration + (x - g.x0) / p);
        dur = Math.max(0.5, snapT(g.shot.start + dur) - g.shot.start);
        g.dur = Math.round(dur * 100) / 100;
        g.clip.style.width = Math.max(6, g.dur * p - 2) + 'px';
        g.clip.querySelector('.du').textContent = g.dur.toFixed(1) + 's';
        return;
      }
      if (g.mode === 'maybe' && Math.abs(x - g.x0) > 6) {
        g.mode = 'move';
        g.clip.classList.add('dragging');
        g.ghost = document.createElement('div');
        g.ghost.className = 'ovs-ghost';
        g.ghost.style.width = g.clip.style.width;
        g.ghost.style.top = (canvas.querySelector('.ovs-video').offsetTop + 3) + 'px';
        canvas.appendChild(g.ghost);
        g.marker = document.createElement('div');
        g.marker.className = 'ovs-insert';
        canvas.appendChild(g.marker);
      }
      if (g.mode === 'move') {
        g.ghost.style.left = (x - parseFloat(g.clip.style.width) / 2) + 'px';
        const t = x / p;
        let before = null;
        for (const s of d.shots) { if ((s.start + s.end) / 2 > t) { before = s; break; } }
        g.before = before ? before.id : null;
        g.marker.style.left = ((before ? before.start : d.total) * p - 1) + 'px';
      }
    });

    const finish = (ev) => {
      const g = S.drag;
      if (!g) return;
      S.drag = null;
      try { canvas.releasePointerCapture(ev.pointerId); } catch (e) { /* ignore */ }
      if (g.mode === 'scrub') { trigger('release', { t: Math.round(S.playhead * 100) / 100 }); return; }
      if (g.mode === 'resize') {
        if (Math.abs(g.dur - g.shot.duration) >= 0.05) trigger('apply', { action: 'duration', shot: g.shot.id, duration: g.dur });
        else g.clip.style.width = Math.max(6, g.shot.duration * p - 2) + 'px';
        return;
      }
      if (g.mode === 'maybe') {
        S.selected = g.shot.id; S.selTr = null; light(d);
        trigger('select', { kind: 'shot', id: g.shot.id });
        return;
      }
      if (g.mode === 'move') {
        g.clip.classList.remove('dragging');
        g.ghost.remove(); g.marker.remove();
        const idx = d.shots.findIndex((s) => s.id === g.shot.id);
        const next = d.shots[idx + 1] ? d.shots[idx + 1].id : null;
        if (g.before !== g.shot.id && g.before !== next) trigger('apply', { action: 'move', shot: g.shot.id, before: g.before });
      }
    };
    canvas.addEventListener('pointerup', finish);
    canvas.addEventListener('pointercancel', finish);

    canvas.addEventListener('dblclick', (ev) => {
      const txt = ev.target.closest('.ovs-txt');
      if (txt && txt.classList.contains('editable')) {
        const cur = txt.dataset.edit;
        const label = txt.dataset.kind === 'chapter'
          ? 'Chapter title (empty = no title on this chapter; the date line stays automatic):'
          : 'Caption for this photo (empty = remove):';
        const val = window.prompt(label, cur);
        if (val !== null && val !== cur) trigger('apply', { action: 'caption', shot: txt.dataset.shot, text: val });
      }
    });

    r.addEventListener('keydown', (ev) => {
      if (ev.target.tagName === 'INPUT') return;
      if ((ev.key === 'Delete' || ev.key === 'Backspace') && S.selected) {
        trigger('apply', { action: 'toggle', shot: S.selected }); ev.preventDefault();
      } else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight') {
        const step = (ev.shiftKey ? 5 : 0.5) * (ev.key === 'ArrowLeft' ? -1 : 1);
        setPlayhead(S.playhead + step, true);
        trigger('release', { t: Math.round(S.playhead * 100) / 100 }); ev.preventDefault();
      } else if (ev.key === 'Home' || ev.key === 'End') {
        setPlayhead(ev.key === 'Home' ? 0 : d.total, true);
        trigger('release', { t: Math.round(S.playhead * 100) / 100 }); ev.preventDefault();
      }
    });
  }

  watch('value', render);
  render();
})();
