import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { createInstructionProxy } from '../lib/instructionProxy.mjs';
import { instructionOriginalPath, isMedicationSlug } from '../lib/medicationPaths.mjs';

const pdf = Buffer.from('%PDF-1.7\nOffline artificial fixture, no medical content.\n%%EOF\n');
const hash = createHash('sha256').update(pdf).digest('hex');
function pdfResponse(overrides = {}) {
  const { body = pdf, status = 200, ...headers } = overrides;
  return new Response(body, { status, headers: { 'content-type': 'application/pdf', 'content-length': String(body.length), etag: `"${hash}"`, ...headers } });
}
function jsonResponse(slug = 'fixture-med', options = {}) {
  return new Response(JSON.stringify({ slug, instructions: [], instruction_originals: [] }), { headers: { 'content-type': 'application/json', ...options } });
}
const request = (path = '', options) => new Request(`http://next.test${path || '/'}`, options);
const make = options => createInstructionProxy({ origin: 'http://backend_instructions:8001', ...options });

test('fixed medication GET forwards only a validated slug/city and no incoming credentials', async () => {
  let call;
  const proxy = make({ fetchImpl: async (...args) => { call = args; return jsonResponse(); } });
  const response = await proxy.medication(request('/catalog-data/medications/fixture-med?city=kzn', { headers: { cookie: 'private=value', authorization: 'secret', range: 'bytes=0-9', 'x-forwarded-host': 'evil.test' } }), 'fixture-med');
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.equal(response.headers.get('x-robots-tag'), 'noindex');
  assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
  assert.equal((await response.json()).slug, 'fixture-med');
  assert.equal(call[0], 'http://backend_instructions:8001/api/medications/fixture-med?city=kzn');
  assert.deepEqual(call[1].headers, { Accept: 'application/json', 'Accept-Encoding': 'identity' });
  assert.equal(call[1].method, 'GET');
  assert.equal(call[1].redirect, 'error');
  assert.equal(call[1].credentials, 'omit');
  assert.equal(call[1].cache, 'no-store');
});

test('medication queries, identities and methods fail closed before fetch', async () => {
  let calls = 0;
  const proxy = make({ fetchImpl: async () => { calls++; return jsonResponse(); } });
  for (const [slug, query] of [
    ['../admin', ''], ['a/b', ''], ['a%2fb', ''], ['a?url=x', ''], ['a'.repeat(241), ''], ['Good', ''],
    ['fixture-med', '?city=unknown'], ['fixture-med', '?city='], ['fixture-med', '?city=msk&city=spb'],
    ['fixture-med', '?url=http://evil.test'], ['fixture-med', '?city=msk&download=true'],
  ]) {
    const response = await proxy.medication(request('/med' + query), slug);
    assert.equal(response.status, 400, `${slug}${query}`);
    assert.equal(response.headers.get('x-robots-tag'), 'noindex');
  }
  for (const method of ['HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']) {
    assert.equal((await proxy.medication(request('/', { method }), 'fixture-med')).status, 405);
  }
  assert.equal(calls, 0);
});

test('all twelve cities and an omitted city are supported independently', async () => {
  const urls = [];
  const proxy = make({ fetchImpl: async url => { urls.push(url); return jsonResponse(); } });
  for (const city of ['', 'msk', 'spb', 'krd', 'nn', 'ekb', 'kzn', 'nsk', 'sam', 'chel', 'ufa', 'rnd', 'vrn']) {
    const response = await proxy.medication(request('/' + (city ? `?city=${city}` : '')), 'fixture-med');
    assert.equal(response.status, 200);
    await response.text();
  }
  assert.equal(urls.length, 13);
  assert.equal(urls[0], 'http://backend_instructions:8001/api/medications/fixture-med');
});

test('production origins have exactly two literal entries, without a loopback exception', async () => {
  let calls = 0;
  for (const origin of ['http://127.0.0.1:8001', 'http://localhost:8001', 'https://backend:8001', 'http://backend:8001/', 'http://backend:8001@evil.test', 'http://backend_instructions:8001/api', 'http://evil.test']) {
    const proxy = make({ origin, fetchImpl: async () => { calls++; return jsonResponse(); } });
    assert.equal((await proxy.medication(request(), 'fixture-med')).status, 503, origin);
  }
  assert.equal(calls, 0);
  for (const origin of ['http://backend:8001', 'http://backend_instructions:8001']) {
    const proxy = make({ origin, fetchImpl: async () => jsonResponse() });
    assert.equal((await (await proxy.medication(request(), 'fixture-med')).json()).slug, 'fixture-med');
  }
});

test('JSON errors, redirects, wrong identities, arrays and invalid content are controlled', async () => {
  const responses = [
    () => new Response('<html>private upstream error</html>', { status: 500 }),
    () => new Response('{}', { headers: { 'content-type': 'text/html' } }),
    () => new Response('{invalid', { headers: { 'content-type': 'application/json' } }),
    () => new Response('[]', { headers: { 'content-type': 'application/json' } }),
    () => jsonResponse('wrong-med'),
    () => new Response(new Uint8Array([0xff]), { headers: { 'content-type': 'application/json' } }),
    () => new Response('{}', { status: 401 }),
    () => new Response(null, { status: 302, headers: { location: 'http://evil.test' } }),
    () => { throw new Error('private upstream exception'); },
  ];
  for (const fetchImpl of responses) {
    const response = await make({ fetchImpl }).medication(request(), 'fixture-med');
    assert.equal(response.status, 502);
    assert.equal(response.headers.get('x-robots-tag'), 'noindex');
    assert.doesNotMatch(await response.text(), /private|evil|wrong-med/);
  }
  for (const status of [404, 503]) {
    const response = await make({ fetchImpl: async () => new Response('private error', { status }) }).medication(request(), 'fixture-med');
    assert.equal(response.status, status);
    assert.doesNotMatch(await response.text(), /private/);
  }
});

test('official relative PDF paths alone become new fixed Next paths', () => {
  assert.equal(instructionOriginalPath('/api/instructions/originals/good_ID-1.pdf'), '/instrukcii/originaly/good_ID-1');
  for (const url of ['https://example.test/api/instructions/originals/good.pdf', '//evil.test/x.pdf', '/api/instructions/originals/../admin.pdf', '/api/instructions/originals/good.pdf?url=x', '/api/instructions/originals/good%2Fadmin.pdf', '/api/instructions/originals/_bad.pdf', '/api/instructions/originals/good.pdf#x', '/api/instructions/originals/' + 'a'.repeat(129) + '.pdf']) assert.equal(instructionOriginalPath(url), null, url);
});

test('safe existing truncated catalog slug shapes retain their exact identity', () => {
  assert.equal(isMedicationSlug('immunoglobulinovyy-kompleksnyy-preparat-dlya-enteralnogo-primeneniya-kip-300-mg-liofilizat-dlya-prigotovleniya-rastvora-'), true);
  assert.equal(isMedicationSlug('gam-kovid-vak-sars-cov--2'), true);
  assert.equal(isMedicationSlug('a'.repeat(122)), true);
  assert.equal(isMedicationSlug('a'.repeat(240)), true);
  assert.equal(isMedicationSlug('a'.repeat(241)), false);
  assert.equal(isMedicationSlug('-leading-hyphen'), false);
});

test('PDF requires complete bytes, strong matching SHA ETag and safe locally generated headers', async () => {
  for (const download of [undefined, 'false', 'true']) {
    let call;
    const proxy = make({ fetchImpl: async (...args) => { call = args; return pdfResponse({ 'set-cookie': 'secret=x', 'content-disposition': 'attachment; filename="evil.html"' }); } });
    const response = await proxy.original(request('/' + (download === undefined ? '' : `?download=${download}`)), 'good_ID-1');
    assert.equal(response.status, 200);
    assert.deepEqual(Buffer.from(await response.arrayBuffer()), pdf);
    assert.equal(response.headers.get('etag'), `"${hash}"`);
    assert.equal(response.headers.get('content-type'), 'application/pdf');
    assert.equal(response.headers.get('content-length'), String(pdf.length));
    assert.equal(response.headers.get('x-robots-tag'), 'noindex');
    assert.equal(response.headers.get('set-cookie'), null);
    assert.equal(response.headers.get('content-disposition'), `${download === 'true' ? 'attachment' : 'inline'}; filename="good_ID-1.pdf"`);
    assert.equal(call[0], `http://backend_instructions:8001/api/instructions/originals/good_ID-1.pdf${download === undefined ? '' : `?download=${download}`}`);
  }
});

test('PDF query and document id validation cannot proxy another upstream path', async () => {
  let calls = 0;
  const proxy = make({ fetchImpl: async () => { calls++; return pdfResponse(); } });
  for (const id of ['', '_bad', '../admin', 'good.pdf', 'good/admin', 'good%2Fadmin', 'a'.repeat(129)]) assert.equal((await proxy.original(request(), id)).status, 400, id);
  for (const query of ['?download=1', '?download=', '?download=True', '?download=true&download=false', '?url=http://evil.test', '?city=msk', '?download=false&admin=true']) assert.equal((await proxy.original(request('/' + query), 'good')).status, 400, query);
  assert.equal(calls, 0);
});

test('HTML, partial responses, incomplete PDF bodies and unsafe transport metadata are rejected', async () => {
  const variants = [
    { 'content-type': 'text/html' }, { etag: '"not-a-sha"' }, { etag: `W/"${hash}"` }, { etag: `"${'0'.repeat(64)}"` },
    { 'content-length': String(pdf.length + 1) }, { 'content-length': String(33 * 1024 * 1024) },
    { 'content-range': `bytes 0-${pdf.length - 1}/${pdf.length}` }, { 'content-encoding': 'gzip' },
    { body: Buffer.from('<html>fake PDF</html>') }, { body: Buffer.from('%PDF-1.7\ntruncated') },
    { status: 206 },
  ];
  for (const variant of variants) {
    const response = await make({ fetchImpl: async () => pdfResponse(variant) }).original(request(), 'good');
    assert.equal(response.status, 502, JSON.stringify(variant));
  }
  for (const field of ['content-length', 'etag']) {
    const upstream = pdfResponse(); upstream.headers.delete(field);
    assert.equal((await make({ fetchImpl: async () => upstream }).original(request(), 'good')).status, 502, field);
  }
});

test('PDF capacity includes unread downstream bodies and is released exactly once on cancellation', async () => {
  let calls = 0;
  const proxy = make({ fetchImpl: async () => { calls++; return pdfResponse(); } });
  const first = await proxy.original(request(), 'one');
  const second = await proxy.original(request(), 'two');
  assert.equal((await proxy.original(request(), 'blocked')).status, 503);
  assert.equal(calls, 2);
  await first.body.cancel();
  const third = await proxy.original(request(), 'three');
  assert.equal(third.status, 200);
  await second.arrayBuffer(); await third.arrayBuffer();
  const last = await proxy.original(request(), 'last');
  assert.equal(last.status, 200); await last.body.cancel();
});

test('JSON concurrency and both stream size limits are bounded', async () => {
  const proxy = make({ fetchImpl: async () => jsonResponse() });
  const pending = [];
  for (let i = 0; i < 8; i++) pending.push(await proxy.medication(request(), 'fixture-med'));
  assert.equal((await proxy.medication(request(), 'fixture-med')).status, 503);
  await Promise.all(pending.map(response => response.body.cancel()));
  for (const kind of ['json', 'pdf']) {
    let cancelled = false;
    const body = new ReadableStream({ start(stream) { stream.enqueue(Buffer.alloc(128)); }, cancel() { cancelled = true; } });
    const headers = kind === 'pdf' ? { 'content-type': 'application/pdf', 'content-length': '64', etag: `"${hash}"` } : { 'content-type': 'application/json' };
    const bounded = make({ jsonLimit: 64, pdfLimit: 64, fetchImpl: async () => new Response(body, { headers }) });
    const result = kind === 'pdf' ? await bounded.original(request(), 'good') : await bounded.medication(request(), 'fixture-med');
    assert.equal(result.status, 502);
    assert.equal(cancelled, true);
  }
});

test('upstream fetch and body deadlines abort work and release capacity for the next request', async () => {
  for (const phase of ['fetch', 'body']) {
    let first = true;
    let aborted = false;
    let cancelled = false;
    const proxy = make({ pdfDeadlineMs: 15, fetchImpl: async (_url, options) => {
      options.signal.addEventListener('abort', () => { aborted = true; });
      if (!first) return pdfResponse();
      first = false;
      if (phase === 'fetch') return new Promise(() => {});
      return new Response(new ReadableStream({ cancel() { cancelled = true; } }), { headers: { 'content-type': 'application/pdf', 'content-length': String(pdf.length), etag: `"${hash}"` } });
    } });
    const response = await proxy.original(request(), 'good');
    assert.equal(response.status, 504, phase);
    assert.equal(aborted, true);
    if (phase === 'body') assert.equal(cancelled, true);
    const next = await proxy.original(request(), 'good');
    assert.equal(next.status, 200); await next.arrayBuffer();
  }
});

test('client cancellation aborts an upstream read; slow downstream timeout releases its slot', async () => {
  const controller = new AbortController();
  let aborted = false, cancelled = false;
  const proxy = make({ fetchImpl: async (_url, options) => {
    options.signal.addEventListener('abort', () => { aborted = true; });
    return new Response(new ReadableStream({ cancel() { cancelled = true; } }), { headers: { 'content-type': 'application/pdf', 'content-length': String(pdf.length), etag: `"${hash}"` } });
  } });
  const pending = proxy.original(request('/', { signal: controller.signal }), 'good');
  await delay(1); controller.abort();
  assert.equal((await pending).status, 408);
  assert.equal(aborted, true); assert.equal(cancelled, true);
  const slow = make({ pdfDeadlineMs: 15, fetchImpl: async () => pdfResponse() });
  const first = await slow.original(request(), 'one');
  const second = await slow.original(request(), 'two');
  assert.equal((await slow.original(request(), 'blocked')).status, 503);
  await delay(25);
  await assert.rejects(first.arrayBuffer()); await assert.rejects(second.arrayBuffer());
  const next = await slow.original(request(), 'next');
  assert.equal(next.status, 200); await next.arrayBuffer();
});
