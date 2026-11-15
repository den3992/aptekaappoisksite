// Run after npm run build. All requests use an isolated local API fixture;
// this suite never queries or changes the production database.
import { before, after, test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const cwd = fileURLToPath(new URL('..', import.meta.url));
const counts = new Map();
let server, app, origin, output = '';
const item = { slug: 'nurofen-test', name: 'Нурофен', form: 'таблетки', dosage: '200 мг', manufacturer: 'Test', variants_count: 1 };
// Artificial fixture strings only: these are not medical instructions.
const instructionDocuments = [
  {
    id:'fixture-document-1', title:'Тестовая инструкция первого РУ', registration_numbers:['РУ-ТЕСТ-1'], version:'fixture-v1',
    approved_at:'2026-01-02', retrieved_at:'2026-11-15T00:00:00Z',
    source:{name:'Тестовый официальный источник',url:'https://example.test/registry/1'}, original_url:'https://example.test/instruction-1.pdf',
    sections:[{key:'fixture',title:'Тестовый раздел',text:'Первый тестовый абзац.\n\n• Первый пункт\n• Второй пункт\n\n<script>alert("fixture")</script>'}],
    bindings:[{gtin:'00000000000001',ru_number:'РУ-ТЕСТ-1',pack_size:'20 шт',form:'тестовая форма А',dosage:'тестовая дозировка А'}],
  },
  {
    id:'fixture-document-2', title:'Тестовый документ второго РУ', document_type:'patient_leaflet', registration_numbers:['РУ-ТЕСТ-2'],
    source:{name:'Второй тестовый источник',url:'javascript:alert(1)'}, original_url:'javascript:alert(2)',
    sections:[{key:'fixture-two',title:'Второй тестовый раздел',text:'Текст второго документа.\n\n3. Третий пункт\n4. Четвёртый пункт'}],
    bindings:[{gtin:'00000000000002',ru_number:'РУ-ТЕСТ-2',pack_size:'20 шт',form:'тестовая форма Б',dosage:'тестовая дозировка Б'}],
  },
];
const listen = server => new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(server.address().port)));

before(async () => {
  server = http.createServer((request, response) => {
    const url = new URL(request.url, 'http://fixture');
    counts.set(url.pathname + url.search, (counts.get(url.pathname + url.search) || 0) + 1);
    response.setHeader('Content-Type', 'application/json');
    const city = url.searchParams.get('city');
    if (city === 'ufa') { response.writeHead(503); response.end('{"detail":"temporary failure"}'); return; }
    if (city === 'rnd' && url.searchParams.has('q')) { response.writeHead(503); response.end('{}'); return; }
    const empty = city === 'ekb';
    if (url.pathname === '/api/categories') {
      response.end(JSON.stringify([
        // A stale zero must not override the category search response.
        {slug:'ot-prostudy',title:'От простуды и гриппа',count:empty || city === 'msk' ? 0 : 90},
        {slug:'obezbolivayuschie',title:'Обезболивающие',count:empty ? 0 : 229},
        {slug:'glaza',title:'Глаза',count:0},
      ]));
    } else if (url.pathname === '/api/search') {
      const category = url.searchParams.get('category');
      const total = empty || category === 'glaza' ? 0 : category === 'ot-prostudy' ? (city === 'spb' ? 90 : 116) : category ? 229 : 4949;
      response.end(JSON.stringify({total, page:Number(url.searchParams.get('page') || 1), page_size:Number(url.searchParams.get('page_size')), items:total ? [item] : []}));
    } else if (url.pathname === '/api/search/suggest') {
      response.end(JSON.stringify([item]));
    } else if (['/api/medications/instruction-test','/api/medications/instruction-pending'].includes(url.pathname)) {
      const hasInstructions = url.pathname.endsWith('/instruction-test');
      response.end(JSON.stringify({
        ...item, slug:hasInstructions ? 'instruction-test' : 'instruction-pending',
        variants:[{pack_size:'20 шт'}], prices_by_city:{}, seo_indexable:false,
        instructions:hasInstructions ? instructionDocuments : [],
        instruction_coverage:{total_variants:3,covered_variants:hasInstructions ? 2 : 0,fully_covered:false},
        instruction_candidates:[{document_type:'patient_leaflet',title:'Непроверенный черновой листок',verification:{status:'draft'},sections:[{key:'draft',title:'Черновик',text:'Этот черновик не подтверждает покрытие.'}]}],
        enrichment:{summary:'Тестовое старое описание.',indications:['Тестовые старые показания.'],contraindications:['Тестовые старые противопоказания.'],how_to_take:'Тестовый старый способ применения.'},
      }));
    } else {
      response.writeHead(404); response.end('{}');
    }
  });
  const apiPort = await listen(server);
  const temporary = http.createServer();
  const port = await listen(temporary);
  await new Promise(resolve => temporary.close(resolve));
  origin = `http://127.0.0.1:${port}`;
  app = spawn(process.execPath, ['node_modules/next/dist/bin/next', 'start', '-H', '127.0.0.1', '-p', String(port)], {
    cwd, env:{...process.env, NODE_ENV:'production', BACKEND_INTERNAL_URL:`http://127.0.0.1:${apiPort}`}, stdio:['ignore','pipe','pipe'],
  });
  app.stdout.on('data', data => { output += data; });
  app.stderr.on('data', data => { output += data; });
  for (let attempt = 0; attempt < 100; attempt++) {
    if (app.exitCode !== null) throw new Error(output);
    try { await fetch(`${origin}/o-servise`); return; } catch { await delay(100); }
  }
  throw new Error(`Next did not start: ${output}`);
});

after(async () => {
  app?.kill('SIGTERM');
  if (server) { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
});

async function page(path) {
  const response = await fetch(origin + path, {headers:{'user-agent':'Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)'}});
  return {status:response.status, html:await response.text()};
}

test('category metadata uses the same total as the server-rendered list', async () => {
  const {status,html} = await page('/msk/kategorii/ot-prostudy');
  assert.equal(status, 200);
  assert.match(html, /<title>[^<]*116 препаратов/);
  assert.match(html, /name="description" content="[^\"]*116 препаратов/);
  assert.doesNotMatch(html, /name="robots" content="[^\"]*noindex/);
  assert.match(html, /href="\/msk\/preparaty\/nurofen-test"/);
  assert.match(html, /rel="canonical" href="https:\/\/aptekaa.ru\/msk\/kategorii\/ot-prostudy"/);
  assert.equal(counts.get('/api/search?page=1&page_size=24&category=ot-prostudy&city=msk'), 1);
});

test('cities remain isolated and a genuinely empty city keeps noindex', async () => {
  const spb = await page('/spb/kategorii/ot-prostudy');
  assert.equal(spb.status, 200);
  assert.match(spb.html, /<title>[^<]*Санкт-Петербурга, 90 препаратов/);
  const empty = await page('/ekb/kategorii/ot-prostudy');
  assert.equal(empty.status, 200);
  assert.match(empty.html, /name="robots" content="noindex, follow"/);
  assert.match(empty.html, /<title>[^<]*0 препаратов/);
});

test('pagination keeps its existing noindex and first-page canonical', async () => {
  const {status,html} = await page('/msk/preparaty?page=2');
  assert.equal(status, 200);
  assert.match(html, /name="robots" content="noindex, follow"/);
  assert.match(html, /rel="canonical" href="https:\/\/aptekaa.ru\/msk\/preparaty"/);
  assert.match(html, /страница 2/);
  assert.match(html, /href="\/msk\/preparaty\/nurofen-test"/);
  assert.equal(counts.get('/api/search?page=2&page_size=48&city=msk'), 1);
});

test('API failure is an HTTP error, not a successful zero catalogue', async () => {
  const {status,html} = await page('/ufa/kategorii/ot-prostudy');
  assert.ok(status >= 500, `unexpected status ${status}`);
  assert.doesNotMatch(html, /0 препаратов/);
});

test('unknown category is a real 404', async () => {
  assert.equal((await page('/msk/kategorii/not-a-category')).status, 404);
});

test('regional header, footer and popular links are correct before JavaScript', async () => {
  const {status,html} = await page('/spb');
  assert.equal(status, 200);
  const header = html.match(/<header\b[\s\S]*?<\/header>/)?.[0];
  const footer = html.match(/<footer\b[\s\S]*?<\/footer>/)?.[0];
  assert.ok(header && footer);
  assert.match(header, /href="\/spb\/kategorii"/);
  assert.doesNotMatch(header, /href="\/msk\//);
  assert.match(footer, /href="\/spb\/preparaty"/);
  assert.doesNotMatch(footer, /href="\/msk\//);
  assert.match(html, /href="\/spb\/preparaty\/nurofen-test"/);
  assert.match(html, /href="\/spb\/kategorii\/ot-prostudy"/);
});

test('failure of optional popular lookups does not fail the homepage', async () => {
  const {status,html} = await page('/rnd');
  assert.equal(status, 200);
  assert.match(html, /href="\/rnd\/kategorii\/obezbolivayuschie"/);
});

test('complete instructions, provenance and every exact binding appear before JavaScript', async () => {
  const {status,html} = await page('/msk/preparaty/instruction-test');
  assert.equal(status, 200);
  const section = html.match(/<section id="instrukciya"[\s\S]*?<\/section>/)?.[0];
  assert.ok(section, 'instruction must be actual SSR HTML, not just an RSC prop');
  assert.match(html, /href="#instrukciya"[^>]*>Инструкция по применению<\/a>/);
  assert.equal((section.match(/data-testid="med-instruction-document"/g) || []).length, 2);
  assert.match(section, /data-document-type="patient_leaflet"[\s\S]*?<h3[^>]*>Листок-вкладыш<\/h3>/);
  assert.match(section, /Тестовый документ второго РУ/);
  assert.doesNotMatch(section, /Непроверенный черновой листок|Этот черновик не подтверждает покрытие/);
  for (const expected of ['Первый тестовый абзац.','Первый пункт','Второй пункт','Текст второго документа.','3. Третий пункт','4. Четвёртый пункт','РУ-ТЕСТ-1','РУ-ТЕСТ-2','00000000000001','00000000000002','тестовая форма А','тестовая форма Б','тестовая дозировка А','тестовая дозировка Б','fixture-v1','02.01.2026','15.11.2026']) assert.ok(section.includes(expected), expected);
  assert.match(section.replace(/<!-- -->/g, ''), /Инструкции подтверждены для 2 из 3 вариантов/);
  assert.match(section, /href="https:\/\/example\.test\/registry\/1"/);
  assert.match(section, /href="https:\/\/example\.test\/instruction-1\.pdf"/);
  assert.match(section, /&lt;script&gt;alert\(&quot;fixture&quot;\)&lt;\/script&gt;/);
  assert.doesNotMatch(section, /<script|href="javascript:/);
  assert.match(section, /<ul\b[\s\S]*?<li>Первый пункт<\/li>/);
  assert.match(section, /<ol\b[\s\S]*?<li>3\. Третий пункт<\/li>/);
  const legacy = html.match(/<section id="o-preparate"[\s\S]*?<\/section>/)?.[0] || '';
  assert.doesNotMatch(legacy, /Тестовое старое описание|Тестовые старые показания|Тестовые старые противопоказания|Тестовый старый способ применения/);
});

test('legacy enrichment is not presented as an official instruction', async () => {
  const {status,html} = await page('/msk/preparaty/instruction-pending');
  assert.equal(status, 200);
  const section = html.match(/<section id="instrukciya"[\s\S]*?<\/section>/)?.[0];
  assert.ok(section);
  assert.match(section, /Официальная инструкция для вариантов этого препарата ещё не подтверждена/);
  assert.doesNotMatch(section, /med-instruction-document|Тестовые старые показания|Тестовый старый способ применения/);
});
