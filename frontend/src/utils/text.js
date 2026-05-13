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

// Legal-form prefixes (RU) that should be stripped from manufacturer names.
// Match at start of string OR at end (sometimes RU form goes after name).
const LEGAL_FORMS = [
  'ОАО', 'ООО', 'ЗАО', 'ПАО', 'АО', 'ОДО', 'ИП',
  'ФГУП', 'ФГБУ', 'ГБУ', 'ГУП', 'ГП',
  'ПФК', 'НПО', 'НПП', 'НПК', 'ПКФ', 'ХФК',
  'OOO', // Latin-look-alike (typo in DB)
];

// Short ALL-CAPS tokens that are likely real abbreviations — keep as-is.
const KEEP_ABBR = new Set([
  'ХФЗ', 'НПО', 'АХФ', 'ХФК', 'РФ', 'МНН', 'ЦМТ',
  'РУС', 'НПП', 'НПК', 'СНГ', 'СПБ',
]);

function titleWord(w) {
  if (!w) return w;
  // pure numeric tokens, punctuation
  if (!/\p{L}/u.test(w)) return w;
  // ALL-CAPS Cyrillic with NO vowels — likely real abbreviation (ХФЗ, НПО, ВДВ)
  if (w === w.toUpperCase() && /^[А-ЯЁ]+$/.test(w) && !/[АЕЁИОУЫЭЮЯ]/.test(w)) return w;
  // Curated abbreviations list — keep
  if (KEEP_ABBR.has(w)) return w;
  // standard title-case
  return w.charAt(0).toLocaleUpperCase('ru-RU') + w.slice(1).toLocaleLowerCase('ru-RU');
}

export function formatManufacturer(s) {
  if (!s || typeof s !== 'string') return s;
  let v = s.trim().replace(/[«»"]/g, '');
  // Strip leading legal form(s), possibly several (e.g. "АО НПО МИКРОГЕН")
  // \b doesn't work with cyrillic in JS regex, so we use lookahead for separator.
  let changed = true;
  while (changed) {
    changed = false;
    for (const lf of LEGAL_FORMS) {
      const re = new RegExp(`^${lf}(?=\\s|[.,]|$)[\\s.,]*`, 'i');
      if (re.test(v)) {
        v = v.replace(re, '');
        changed = true;
      }
    }
  }
  // Strip trailing legal form ("ГЕДЕОН РИХТЕР ОАО")
  for (const lf of LEGAL_FORMS) {
    const re = new RegExp(`[\\s,]+${lf}\\s*$`, 'i');
    v = v.replace(re, '');
  }
  v = v.trim().replace(/^[,\s]+/, '').replace(/[,\s]+$/, '');
  if (!v) return s; // fallback if we stripped everything
  // Title-case only if input was mostly upper
  if (!isAllCaps(s)) return v;
  return v.split(/(\s+|[-/])/).map(titleWord).join('');
}
