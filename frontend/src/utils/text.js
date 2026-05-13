// Text formatting helpers used across the UI.
// The DB keeps drug names/forms/manufacturers in ALL CAPS for some sources
// (e.g. ESKLP registry). We don't mutate the DB — instead we normalise
// casing at render-time.

const isAllCaps = (s) => {
  if (!s || typeof s !== 'string') return false;
  const letters = s.match(/\p{L}/gu) || [];
  if (letters.length < 3) return false;
  const upper = letters.filter((c) => c === c.toUpperCase() && c !== c.toLowerCase());
  return upper.length / letters.length >= 0.85;
};

// Title-case ALL-CAPS strings: first letter of each word uppercase, rest lower.
// Keeps already-mixed-case strings untouched.
// Preserves short tokens that look like units/dosages (e.g. "мг", "мл", "МНН").
export function formatName(s) {
  if (!s || typeof s !== 'string') return s;
  if (!isAllCaps(s)) return s;
  return s
    .toLocaleLowerCase('ru-RU')
    .replace(/(^|[\s\-/(])(\p{L})/gu, (m, p1, p2) => p1 + p2.toLocaleUpperCase('ru-RU'));
}
