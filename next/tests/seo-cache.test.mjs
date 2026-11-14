import test from 'node:test';
import assert from 'node:assert/strict';
import { timedCache } from '../lib/timedCache.js';

test('a zero category count expires and a price import becomes visible', async () => {
  let time = 0;
  let count = 0;
  let calls = 0;
  const get = timedCache(async () => { calls++; return count; }, 60_000, () => time);
  assert.equal(await get('msk'), 0);
  count = 116;
  assert.equal(await get('msk'), 0);
  time = 60_000;
  assert.equal(await get('msk'), 116);
  assert.equal(calls, 2);
});

test('concurrent requests share one lookup, with separate city keys', async () => {
  let calls = 0;
  const get = timedCache(async city => { calls++; return city === 'msk' ? 116 : 90; }, 60_000);
  const values = await Promise.all([get('msk'), get('msk'), get('spb'), get('spb')]);
  assert.deepEqual(values, [116, 116, 90, 90]);
  assert.equal(calls, 2);
});

test('a failed refresh rejects and retries instead of storing false empty data', async () => {
  let time = 0;
  let fail = false;
  const get = timedCache(async () => {
    if (fail) throw new Error('backend unavailable');
    return 229;
  }, 60_000, () => time);
  assert.equal(await get('msk'), 229);
  time = 60_000;
  fail = true;
  await assert.rejects(get('msk'), /backend unavailable/);
  fail = false;
  assert.equal(await get('msk'), 229);
});
