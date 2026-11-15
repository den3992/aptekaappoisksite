// Run against a built standalone Next image with no external network:
// --add-host backend_instructions:127.0.0.1 (the production origin is unchanged).
import { before, after, test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const cwd = fileURLToPath(new URL('..', import.meta.url));
const pdf = Buffer.from('%PDF-1.7\nArtificial offline runtime fixture only.\n%%EOF\n');
const sha = createHash('sha256').update(pdf).digest('hex');
let api, app, origin, output = '', cancelledUpstream = false, cancelStarted;
const cancelObserved = new Promise(resolve => { cancelStarted = resolve; });
const calls = [];
const med = {
  slug: 'bff-fixture', name: 'Тестовая карточка маршрута', form: 'тестовая форма', dosage: 'тестовая дозировка', manufacturer: 'Fixture',
  variants: [{ pack_size: 'fixture', gtin: '00000000000001', ru_number: 'РУ-ТЕСТ' }], prices_by_city: {}, seo_indexable: false,
  instructions: [], instruction_coverage: { total_variants: 1, covered_variants: 0, fully_covered: false },
  instruction_originals: [{
    id: 'fixture-pdf', title: 'Подтвержденный тестовый PDF', document_type: 'patient_leaflet', content_format: 'official_original_pdf',
    registration_numbers: ['РУ-ТЕСТ'], original_sha256: sha, download_url: '/api/instructions/originals/fixture-pdf.pdf',
    source: { name: 'Тестовый первичный источник', url: 'https://example.test/official' }, version: 'fixture-v1',
    verification: { status: 'verified', verified_at: '2026-11-15T00:00:00Z' }, matched_variants: [{ gtin: '00000000000001', ru_number: 'РУ-ТЕСТ' }],
  }], instruction_original_coverage: { total_variants: 1, covered_variants: 1, fully_covered: true },
};
const listen = (server, port = 0) => new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', () => resolve(server.address().port)); });

before(async () => {
  api = http.createServer((request, response) => {
    const url = new URL(request.url, 'http://fixture');
    calls.push({ path: url.pathname + url.search, headers: request.headers });
    if (url.pathname.startsWith('/api/instructions/originals/')) {
      if (url.pathname.endsWith('/cancel.pdf')) {
        response.writeHead(200, { 'content-type': 'application/pdf', 'content-length': pdf.length, etag: `"${sha}"` });
        response.write(pdf.subarray(0, 5));
        response.once('close', () => { cancelledUpstream = true; });
        cancelStarted(); return;
      }
      response.writeHead(200, { 'content-type': 'application/pdf', 'content-length': pdf.length, etag: `"${sha}"`, 'set-cookie': 'upstream=private' });
      response.end(pdf); return;
    }
    response.setHeader('content-type', 'application/json');
    if (url.pathname === '/api/medications/bff-fixture') { response.end(JSON.stringify(med)); return; }
    if (url.pathname === '/api/categories') { response.end('[]'); return; }
    // Optional legacy APIs are unavailable. Hydration must still retain med.
    response.writeHead(503); response.end('{"detail":"legacy optional API unavailable"}');
  });
  await listen(api, 8001);
  const temporary = http.createServer();
  const port = await listen(temporary);
  await new Promise(resolve => temporary.close(resolve));
  origin = `http://127.0.0.1:${port}`;
  const entrypoint = existsSync(new URL('../server.js', import.meta.url)) ? ['server.js'] : ['node_modules/next/dist/bin/next', 'start', '-H', '127.0.0.1', '-p', String(port)];
  app = spawn(process.execPath, entrypoint, { cwd, env: { ...process.env, NODE_ENV: 'production', HOSTNAME: '127.0.0.1', PORT: String(port), BACKEND_INTERNAL_URL: 'http://backend_instructions:8001' }, stdio: ['ignore', 'pipe', 'pipe'] });
  app.stdout.on('data', data => { output += data; }); app.stderr.on('data', data => { output += data; });
  for (let attempt = 0; attempt < 100; attempt++) {
    if (app.exitCode !== null) throw new Error(output);
    try { await fetch(origin + '/o-servise'); return; } catch { await delay(100); }
  }
  throw new Error('Next did not start: ' + output);
});

after(async () => {
  app?.kill('SIGTERM');
  if (api) { api.closeAllConnections(); await new Promise(resolve => api.close(resolve)); }
});

test('actual Next medication route uses the allowlisted sidecar origin and returns unmodified verified data', async () => {
  const response = await fetch(origin + '/catalog-data/medications/bff-fixture?city=spb', { headers: { cookie: 'secret=value', authorization: 'secret', range: 'bytes=0-5' } });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('x-robots-tag'), 'noindex');
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.deepEqual(await response.json(), med);
  const upstream = calls.find(call => call.path === '/api/medications/bff-fixture?city=spb');
  assert.ok(upstream); assert.equal(upstream.headers.cookie, undefined); assert.equal(upstream.headers.authorization, undefined); assert.equal(upstream.headers.range, undefined);
});

test('actual Next original route delivers the whole verified SHA file and its own disposition', async () => {
  for (const suffix of ['', '?download=true', '?download=false']) {
    const response = await fetch(origin + '/instrukcii/originaly/fixture-pdf' + suffix);
    assert.equal(response.status, 200);
    assert.deepEqual(Buffer.from(await response.arrayBuffer()), pdf);
    assert.equal(response.headers.get('x-robots-tag'), 'noindex');
    assert.equal(response.headers.get('etag'), `"${sha}"`);
    assert.equal(response.headers.get('set-cookie'), null);
    assert.equal(response.headers.get('content-disposition'), `${suffix === '?download=true' ? 'attachment' : 'inline'}; filename="fixture-pdf.pdf"`);
  }
});

test('actual Next routes reject unknown queries and every method other than GET with noindex', async () => {
  for (const path of ['/catalog-data/medications/bff-fixture?city=msk&city=spb', '/catalog-data/medications/bff-fixture?url=http://evil.test', '/instrukcii/originaly/fixture-pdf?download=1', '/instrukcii/originaly/fixture-pdf?url=http://evil.test']) {
    const response = await fetch(origin + path); assert.equal(response.status, 400); assert.equal(response.headers.get('x-robots-tag'), 'noindex');
  }
  for (const path of ['/catalog-data/medications/bff-fixture', '/instrukcii/originaly/fixture-pdf']) {
    for (const method of ['HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']) {
      const response = await fetch(origin + path, { method });
      assert.equal(response.status, 405); assert.equal(response.headers.get('x-robots-tag'), 'noindex'); assert.equal(response.headers.get('allow'), 'GET');
    }
  }
});

test('actual server-rendered page links to the new PDF route before JavaScript', async () => {
  const response = await fetch(origin + '/msk/preparaty/bff-fixture');
  assert.equal(response.status, 200);
  const html = await response.text();
  const section = html.match(/<section id="instrukciya-pdf"[\s\S]*?<\/section>/)?.[0];
  assert.ok(section);
  assert.match(section, /href="\/instrukcii\/originaly\/fixture-pdf"/);
  assert.match(section, /href="\/instrukcii\/originaly\/fixture-pdf\?download=true"/);
});

test('actual client disconnect cancels the upstream PDF read promptly', async () => {
  const controller = new AbortController();
  const pending = fetch(origin + '/instrukcii/originaly/cancel', { signal: controller.signal });
  const rejection = assert.rejects(pending);
  await Promise.race([cancelObserved, delay(2000).then(() => { throw new Error('upstream did not start'); })]);
  controller.abort(); await rejection;
  for (let attempt = 0; attempt < 100 && !cancelledUpstream; attempt++) await delay(10);
  assert.equal(cancelledUpstream, true, 'the upstream socket must close after downstream cancellation');
});
