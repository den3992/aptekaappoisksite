// Share in-flight lookups, but never retain an old catalogue for a process's
// entire lifetime. Failed loads are not cached as empty successful responses.
export function timedCache(load, ttlMs, now = Date.now) {
  const entries = new Map();
  const pending = new Map();
  return async function get(key) {
    const entry = entries.get(key);
    if (entry && now() < entry.expiresAt) return entry.value;
    if (pending.has(key)) return pending.get(key);
    const request = Promise.resolve().then(() => load(key)).then(value => {
      entries.set(key, { value, expiresAt: now() + ttlMs });
      return value;
    }).finally(() => pending.delete(key));
    pending.set(key, request);
    return request;
  };
}
