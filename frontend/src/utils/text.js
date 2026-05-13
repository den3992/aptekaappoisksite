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
  'ОАО', 'ООО', 'ЗАО', 'ПАО', 'НАО', 'АО', 'ОДО', 'ИП',
  'ФГУП', 'ФГБУ', 'ГБУ', 'ГУП', 'ГП', 'ФКП',
  'ПФК', 'НПО', 'НПП', 'НПК', 'ПКФ', 'ХФК', 'ФП',
  'OOO', 'AO', 'OAO', 'PAO', // Latin look-alikes used by some scrapers
];

// "Weak" canonical roots — too generic to use as a group key alone.
// When formatManufacturer returns one of these as the first word, we extend
// the canonical key with the next word to avoid merging unrelated companies.
const WEAK_ROOTS = new Set([
  'фирма', 'завод', 'фабрика', 'комбинат', 'институт', 'центр',
  'предприятие', 'объединение', 'компания', 'корпорация',
  'фармацевтический', 'фармацевтическая',
]);

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

// Canonical "group root" for a manufacturer. Used to merge duplicate
// medication records that belong to the same pharma group but were registered
// by different legal entities (e.g. "Велфарм" + "Велфарм-М" → Велфарм).
//
// Returns a lowercase token suitable as a map/group key.
export function canonicalManufacturer(s) {
  const stripped = formatManufacturer(s);
  if (!stripped) return '';
  // Take the first dash-delimited token (drops "-М", "-Лексредства", "-Уфавита", "-Тюмень")
  // and the first whitespace-delimited token (drops trailing " Фарм", " М").
  const tokens = stripped.split(/[-/]/)[0].trim().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return '';
  let root = tokens[0].toLocaleLowerCase('ru-RU');
  // If first word is too generic (e.g. "ФИРМА"), include the next word
  // so "Фирма Здоровье" and "Фирма Фермент" don't collapse together.
  if (WEAK_ROOTS.has(root) && tokens.length > 1) {
    root = root + ' ' + tokens[1].toLocaleLowerCase('ru-RU');
  }
  return root;
}

// Group key for medication records that should appear as ONE search result.
// We dedupe by (name + form + dosage + canonical manufacturer group).
export function medGroupKey(m) {
  return [
    (m.name || '').toLocaleLowerCase('ru-RU').trim(),
    (m.form || '').toLocaleLowerCase('ru-RU').trim(),
    (m.dosage || '').toLocaleLowerCase('ru-RU').trim(),
    canonicalManufacturer(m.manufacturer),
  ].join('|');
}

// Deduplicate a list of meds: items sharing the same (name/form/dosage/group)
// are merged. The first item wins as the representative; other manufacturers
// from the same group are collected into `also_manufacturers` for display.
export function dedupeMeds(items) {
  if (!Array.isArray(items)) return items;
  const seen = new Map();
  for (const it of items) {
    const k = medGroupKey(it);
    if (!seen.has(k)) {
      seen.set(k, { ...it, also_manufacturers: [] });
    } else {
      const head = seen.get(k);
      const mfr = it.manufacturer;
      if (mfr && mfr !== head.manufacturer && !head.also_manufacturers.includes(mfr)) {
        head.also_manufacturers.push(mfr);
      }
    }
  }
  return Array.from(seen.values());
}

