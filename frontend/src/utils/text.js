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

// Foreign legal-form suffixes (anywhere in the string) — used to detect
// "tail" after a comma that should be stripped (e.g. "КРКА, Д.Д., НОВО МЕСТО").
// Each entry is matched as a whole token (Cyrillic-aware).
const FOREIGN_LEGAL_TOKENS = [
  'Д.Д.', 'Д.О.О.', 'СП. З.О.О.', 'З.О.О.', 'Н.В.', 'С.А.', 'С.А.У.',
  'С.П.А.', 'С.Р.Л.', 'К.С.', 'К.Г.', 'К.Г.А.А.', 'М.Б.Х.',
  'ГМБХ', 'ЛТД.', 'ЛТД', 'СПА', 'АГ', 'СА', 'СЕ',
  'GMBH', 'LTD.', 'LTD', 'LLC', 'INC.', 'INC', 'PLC',
  'BV', 'B.V.', 'AG', 'A.G.', 'SA', 'S.A.', 'SAU', 'S.A.U.',
  'SARL', 'S.A.R.L.', 'SRL', 'S.R.L.', 'SPA', 'S.P.A.',
  'KG', 'KGAA', 'CO.', 'CO', 'AB', 'OY', 'KK', 'KFT',
  'COMPANY', 'COMPAGNIE', 'CORP', 'CORPORATION',
  'ARZNEIMITTEL', 'PHARMA', 'PHARMACEUTICALS', 'HEALTHCARE',
];

// Brand-override patterns: when manufacturer matches one of these regexes,
// return the canonical brand name directly (skipping the generic stripper).
// Patterns are tested case-insensitively against the FULL trimmed string.
// Order matters: more specific patterns should go first.
const BRAND_OVERRIDES = [
  // Russian-language uppercase variants from ЕСКЛП registry
  [/(^|[\s,])КРКА($|[\s,])/i, 'KRKA'],
  [/РЕКИТТ\s+БЕНКИЗЕР/i, 'Reckitt Benckiser'],
  [/ГЕДЕОН\s+РИХТЕР/i, 'Gedeon Richter'],
  [/САНОФИ(-АВЕНТИС)?(?![А-Я])/i, 'Sanofi'],
  [/НОВАРТИС/i, 'Novartis'],
  [/(ТАКЕДА|НИКОМЕД)/i, 'Takeda'],
  [/ПФАЙЗЕР/i, 'Pfizer'],
  [/ГЛАКСОСМИТКЛЯЙН/i, 'GSK'],
  [/ХЕЙЛКАЙР|ХЭЛЕОН|HALEON/i, 'Haleon'],
  [/(ЯНССЕН|КЕНВЬЮ|KENVUE)/i, 'Kenvue'],
  [/БЕРИНГЕР\s+ИНГЕЛЬХАЙМ/i, 'Boehringer Ingelheim'],
  [/ШТАДА|STADA|НИЖФАРМ/i, 'Stada'],
  [/(ЮНИК\s+ФАРМАСЬЮТИКАЛ|ЦИПЛА|CIPLA)/i, 'Cipla'],
  [/ТЕВА(?![А-Я])/i, 'Teva'],
  [/АСТРАЗЕНЕКА|ASTRAZENECA/i, 'AstraZeneca'],
  [/БАЙЕР|BAYER/i, 'Bayer'],
  [/ЭББОТТ|ABBOTT/i, 'Abbott'],
  [/БИОНОРИКА|BIONORICA/i, 'Bionorica'],
  [/КРЕВЕЛЬ\s+МОЙЗЕЛЬБАХ|KREWEL/i, 'Krewel Meuselbach'],
  [/УРСАФАРМ|URSAPHARM/i, 'Ursapharm'],
  [/МАТЕРИА\s+МЕДИКА/i, 'Materia Medica'],
  [/ФИРН\s+М/i, 'Фирн-М'],
  [/ЦИТОМЕД/i, 'Цитомед'],
  [/СОФАРИМЕКС/i, 'Sofarimex'],
  [/МЕРК(?:\s+КГАА)?/i, 'Merck'],
  [/ФАРМСТАНДАРТ/i, 'Фармстандарт'],
  [/(^|\s)ОЗОН(\s+ФАРМ)?($|\s|,)/i, 'Озон'],
  [/КАНОНФАРМА/i, 'Канонфарма'],
  [/ВЕРТЕКС/i, 'Вертекс'],
  [/АКРИХИН/i, 'Акрихин'],
  [/БИОХИМИК/i, 'Биохимик'],
  [/ВЕЛФАРМ/i, 'Велфарм'],
  [/АВВА\s+РУС/i, 'АВВА РУС'],
  [/НПО\s+МИКРОГЕН|МИКРОГЕН/i, 'Микроген'],
  [/ОТИСИФАРМ|ОТЦИФАРМ/i, 'Otcpharm'],
  [/ОТЦФАРМ/i, 'Otcpharm'],
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
  const trimmed = s.trim().replace(/[«»"]/g, '');

  // 1. Brand-override fast-path: known multi-word brand names like
  //    "АО КРКА, Д.Д., НОВО МЕСТО" → "KRKA".
  for (const [re, brand] of BRAND_OVERRIDES) {
    if (re.test(trimmed)) return brand;
  }

  let v = trimmed;
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

  // 2. If a comma is followed by a foreign legal token anywhere downstream,
  //    cut at the first comma (drops "Д.Д., НОВО МЕСТО" etc.).
  const commaIdx = v.indexOf(',');
  if (commaIdx > 0) {
    const tail = v.slice(commaIdx + 1).toUpperCase();
    const tailHasLegal = FOREIGN_LEGAL_TOKENS.some((tok) => {
      // exact token match in tail (delimited by space/comma/dot)
      const re = new RegExp(`(^|[\\s,.])${tok.replace(/\./g, '\\.')}(?=$|[\\s,.])`);
      return re.test(tail);
    });
    if (tailHasLegal) v = v.slice(0, commaIdx);
  }

  // 3. Trailing foreign legal tokens (e.g. "САНОФИ-АВЕНТИС СП. З.О.О.").
  for (const tok of FOREIGN_LEGAL_TOKENS) {
    const re = new RegExp(`[\\s,]+${tok.replace(/\./g, '\\.')}\\s*$`, 'i');
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

