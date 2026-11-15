import { createHash } from 'node:crypto';
import { instructionDocumentIdPattern, isMedicationSlug } from './medicationPaths.mjs';

const origins = new Set(['http://backend:8001', 'http://backend_instructions:8001']);
const cities = new Set(['msk', 'spb', 'krd', 'nn', 'ekb', 'kzn', 'nsk', 'sam', 'chel', 'ufa', 'rnd', 'vrn']);
const commonHeaders = { 'X-Robots-Tag': 'noindex', 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store' };

function failure(status) {
  const messages = { 400: 'Invalid request', 404: 'Not found', 405: 'Method not allowed', 408: 'Request cancelled', 502: 'Invalid upstream response', 503: 'Temporarily unavailable', 504: 'Upstream timeout' };
  return new Response(JSON.stringify({ detail: messages[status] }), {
    status, headers: { ...commonHeaders, 'Content-Type': 'application/json; charset=utf-8', ...(status === 405 ? { Allow: 'GET' } : {}), ...(status === 503 ? { 'Retry-After': '1' } : {}) },
  });
}

export function rejectInstructionProxyMethod() { return failure(405); }

function queryValue(request, allowed) {
  const params = new URL(request.url).searchParams;
  for (const key of params.keys()) {
    if (!allowed.includes(key) || params.getAll(key).length !== 1) throw new Error('query');
  }
  return params;
}

function abortable(promise, signal) {
  return new Promise((resolve, reject) => {
    const abort = () => reject(new Error('aborted'));
    signal.addEventListener('abort', abort, { once: true });
    Promise.resolve(promise).then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
    if (signal.aborted) abort();
  });
}

function cancelBody(body) {
  if (body && !body.locked) void body.cancel().catch(() => {});
}

async function readBounded(response, limit, signal, requireLength) {
  const declared = response.headers.get('content-length');
  if ((requireLength && declared === null) || (declared !== null && (!/^[1-9]\d*$/.test(declared) || Number(declared) > limit))) {
    cancelBody(response.body);
    throw new Error('length');
  }
  if (!response.body) throw new Error('body');
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await abortable(reader.read(), signal);
      if (done) break;
      size += value.byteLength;
      if (size > limit) throw new Error('limit');
      chunks.push(Buffer.from(value));
    }
    if (!size || (declared !== null && size !== Number(declared))) throw new Error('length');
    return Buffer.concat(chunks, size);
  } catch (error) {
    void reader.cancel().catch(() => {});
    throw error;
  } finally {
    reader.releaseLock();
  }
}

// Dependencies are injectable for offline tests. The upstream origin allowlist
// is always enforced, including with a supplied fetch implementation.
export function createInstructionProxy({
  fetchImpl = (...args) => fetch(...args),
  origin = () => process.env.BACKEND_INTERNAL_URL || 'http://backend:8001',
  jsonLimit = 4 * 1024 * 1024, pdfLimit = 32 * 1024 * 1024,
  jsonDeadlineMs = 20_000, pdfDeadlineMs = 30_000,
} = {}) {
  let activeJson = 0;
  let activePdf = 0;

  async function serve(request, upstreamPath, kind, id, download = false) {
    if (request.signal.aborted) return failure(408);
    const base = typeof origin === 'function' ? origin() : origin;
    if (!origins.has(base)) return failure(503);
    const pdf = kind === 'pdf';
    if ((pdf && activePdf >= 2) || (!pdf && activeJson >= 8)) return failure(503);
    if (pdf) activePdf++; else activeJson++;
    const controller = new AbortController();
    let released = false;
    let handedOff = false;
    let deadlineExpired = false;
    const deadline = setTimeout(() => { deadlineExpired = true; controller.abort(); }, pdf ? pdfDeadlineMs : jsonDeadlineMs);
    const cancel = () => controller.abort();
    request.signal.addEventListener('abort', cancel, { once: true });
    let upstream;
    function release() {
      if (released) return;
      released = true;
      controller.abort();
      cancelBody(upstream?.body);
      clearTimeout(deadline);
      request.signal.removeEventListener('abort', cancel);
      if (pdf) activePdf--; else activeJson--;
    }
    function deliver(body, headers) {
      if (controller.signal.aborted) throw new Error('aborted');
      let buffer = body;
      let offset = 0;
      let streamController;
      const finish = () => {
        buffer = null;
        controller.signal.removeEventListener('abort', abortDelivery);
        release();
      };
      const abortDelivery = () => { streamController.error(new Error('Response cancelled')); finish(); };
      const stream = new ReadableStream({
        start(stream) { streamController = stream; controller.signal.addEventListener('abort', abortDelivery, { once: true }); },
        pull(stream) {
          if (!buffer) return;
          const end = Math.min(offset + 64 * 1024, buffer.length);
          // Copy this bounded chunk: a subarray would retain the complete
          // backing PDF buffer while a slow client holds the final chunk.
          stream.enqueue(new Uint8Array(buffer.subarray(offset, end)));
          offset = end;
          if (offset === buffer.length) { stream.close(); finish(); }
        },
        cancel() { finish(); },
      }, { highWaterMark: 0 });
      const response = new Response(stream, { status: 200, headers });
      handedOff = true;
      return response;
    }
    try {
      const lookup = Promise.resolve(fetchImpl(base + upstreamPath, {
        method: 'GET', headers: { Accept: pdf ? 'application/pdf' : 'application/json', 'Accept-Encoding': 'identity' },
        redirect: 'error', cache: 'no-store', credentials: 'omit', signal: controller.signal,
      })).then(response => {
        if (controller.signal.aborted) { cancelBody(response.body); throw new Error('aborted'); }
        return response;
      });
      upstream = await abortable(lookup, controller.signal);
      if (upstream.status !== 200) {
        cancelBody(upstream.body);
        return failure(upstream.status === 404 ? 404 : upstream.status === 503 ? 503 : 502);
      }
      const type = (upstream.headers.get('content-type') || '').split(';', 1)[0].trim().toLowerCase();
      if (type !== (pdf ? 'application/pdf' : 'application/json') || upstream.headers.has('content-range') || !['', 'identity'].includes(upstream.headers.get('content-encoding') || '')) {
        throw new Error('headers');
      }
      const etag = pdf && upstream.headers.get('etag')?.match(/^"([a-f0-9]{64})"$/i);
      if (pdf && !etag) throw new Error('etag');
      const body = await readBounded(upstream, pdf ? pdfLimit : jsonLimit, controller.signal, pdf);
      if (pdf) {
        if (body.subarray(0, 5).toString('ascii') !== '%PDF-' || !/%%EOF[\t\n\f\r ]*$/.test(body.subarray(-1024).toString('latin1')) || createHash('sha256').update(body).digest('hex') !== etag[1].toLowerCase()) throw new Error('pdf');
        return deliver(body, {
          ...commonHeaders, 'Content-Type': 'application/pdf', 'Content-Length': String(body.length),
          'Content-Disposition': `${download ? 'attachment' : 'inline'}; filename="${id}.pdf"`,
          ETag: `"${etag[1].toLowerCase()}"`, 'Cache-Control': 'public, max-age=86400, immutable',
        });
      }
      const data = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(body));
      if (!data || typeof data !== 'object' || Array.isArray(data) || data.slug !== id) throw new Error('json');
      return deliver(body, { ...commonHeaders, 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': String(body.length) });
    } catch {
      return failure(deadlineExpired ? 504 : request.signal.aborted ? 408 : 502);
    } finally {
      if (!handedOff) release();
    }
  }

  return {
    async medication(request, slug) {
      if (request.method !== 'GET') return failure(405);
      if (!isMedicationSlug(slug)) return failure(400);
      let params;
      try {
        params = queryValue(request, ['city']);
        if (params.has('city') && !cities.has(params.get('city'))) return failure(400);
      } catch { return failure(400); }
      return serve(request, `/api/medications/${slug}${params.has('city') ? `?city=${params.get('city')}` : ''}`, 'json', slug);
    },
    async original(request, documentId) {
      if (request.method !== 'GET') return failure(405);
      if (typeof documentId !== 'string' || !instructionDocumentIdPattern.test(documentId)) return failure(400);
      let params;
      try {
        params = queryValue(request, ['download']);
        if (params.has('download') && !['true', 'false'].includes(params.get('download'))) return failure(400);
      } catch { return failure(400); }
      const download = params.get('download') === 'true';
      return serve(request, `/api/instructions/originals/${documentId}.pdf${params.has('download') ? `?download=${params.get('download')}` : ''}`, 'pdf', documentId, download);
    },
  };
}

export const instructionProxy = createInstructionProxy();
