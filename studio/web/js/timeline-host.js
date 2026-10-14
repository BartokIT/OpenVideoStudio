// Hosts studio/ui/timeline.js. That script is written against a small
// component API (element, trigger, props, watch — originally Gradio's
// js_on_load environment); this provides it, so the timeline stays a single
// self-contained file.

export async function mountTimeline(host, handlers) {
  const code = await (await fetch('/ui/timeline.js', { cache: 'no-store' })).text();
  const props = { value: null };
  const watchers = [];
  const watch = (_names, cb) => { watchers.push(cb); };
  const trigger = (event, data) => { const fn = handlers[event]; if (fn) fn(data || {}); };
  // eslint-disable-next-line no-new-func
  new Function('element', 'trigger', 'props', 'server', 'upload', 'watch', code)(host, trigger, props, {}, null, watch);
  return {
    set(value) { props.value = value; for (const cb of watchers) cb(); },
    get value() { return props.value; },
  };
}
