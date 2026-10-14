// JSON API client and job polling.
import { sleep } from './dom.js';

async function request(method, url, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* not json */ }
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  const type = r.headers.get('content-type') || '';
  return type.includes('json') ? r.json() : r;
}

export const get = (url) => request('GET', url);
export const post = (url, body = {}) => request('POST', url, body);
export const put = (url, body = {}) => request('PUT', url, body);
export const upload = (url, formData) => request('POST', url, formData);

/** Waits for a job started by `started` (a promise of the job JSON),
 *  reporting progress; resolves with its result or throws its error. */
export async function runJob(started, onProgress) {
  let j = await started;
  let wait = 150;
  while (j.status === 'queued' || j.status === 'running') {
    onProgress?.(j);
    await sleep(wait);
    wait = Math.min(wait + 100, 500);
    j = await get(`/api/jobs/${j.id}`);
  }
  onProgress?.(j);
  if (j.status === 'error') throw new Error(j.error || 'Failed');
  return j.result;
}
