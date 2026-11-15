import test from 'node:test';
import assert from 'node:assert/strict';
import axios from 'axios';

test('actual fetchMed uses the new browser route for mount and city refresh while SSR retains runtime upstream', async () => {
  const adapter = axios.defaults.adapter;
  const previousWindow = globalThis.window;
  const previousOrigin = process.env.BACKEND_INTERNAL_URL;
  const calls = [];
  axios.defaults.adapter = async config => {
    calls.push(config);
    return { data: { slug: 'fixture-med', instructions: [{ id: 'verified-fixture' }] }, status: 200, statusText: 'OK', headers: {}, config };
  };
  try {
    delete globalThis.window;
    process.env.BACKEND_INTERNAL_URL = 'http://backend_instructions:8001';
    const server = await import('../api/client.js?server-fixture');
    await server.fetchMed('fixture-med', 'msk');
    assert.equal(calls.at(-1).baseURL, 'http://backend_instructions:8001/api');
    assert.equal(calls.at(-1).url, '/medications/fixture-med');
    globalThis.window = {};
    const browser = await import('../api/client.js?browser-fixture');
    for (const city of ['msk', 'spb']) {
      const controller = new AbortController();
      const data = await browser.fetchMed('fixture-med', city, { signal: controller.signal });
      assert.equal(data.instructions[0].id, 'verified-fixture');
      assert.equal(calls.at(-1).url, '/catalog-data/medications/fixture-med');
      assert.equal(calls.at(-1).baseURL, undefined);
      assert.equal(calls.at(-1).params.city, city);
      assert.equal(calls.at(-1).signal, controller.signal);
    }
    await browser.fetchAnalogs('fixture-med', 8);
    assert.equal(calls.at(-1).baseURL, '/api');
    assert.equal(calls.at(-1).url, '/medications/fixture-med/analogs');
  } finally {
    axios.defaults.adapter = adapter;
    if (previousWindow === undefined) delete globalThis.window; else globalThis.window = previousWindow;
    if (previousOrigin === undefined) delete process.env.BACKEND_INTERNAL_URL; else process.env.BACKEND_INTERNAL_URL = previousOrigin;
  }
});
