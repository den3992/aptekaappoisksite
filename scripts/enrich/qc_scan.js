// QC scan: find artefacts/bugs in all `enrichment` documents in medications.
// Categories:
//  - english_words:     latin letters in summary/indications/contraindications/how_to_take
//  - leading_ws:        leading whitespace (regular or nbsp) in list items
//  - trailing_ws:       trailing whitespace in list items or strings
//  - markdown_wrap:     ```/```json wrappers leaked
//  - inline_md:         **bold** / __bold__ / *ital* markers
//  - missing_field:     summary/indications/contraindications/how_to_take/disclaimer missing/empty
//  - short_summary:     summary < 30 chars
//  - empty_list_item:   list contains empty/whitespace-only string
//  - dup_in_list:       same item appears twice in indications/contraindications
//  - tiny_list:         indications has <2 items or contraindications has <2 items
//  - missing_close:     how_to_take doesn't end with required closer phrase

const LATIN = /[A-Za-z]/;
const NBSP_LEADING = /^[\s\u00a0]+/;
const NBSP_TRAILING = /[\s\u00a0]+$/;
const MD_WRAP = /^```|```$/;
const INLINE_MD = /(\*\*|__|`[^`]+`)/;
const CLOSER = "Точную дозировку и продолжительность курса определяет врач";

const issues = {
  english_words: [],
  leading_ws: [],
  trailing_ws: [],
  markdown_wrap: [],
  inline_md: [],
  missing_field: [],
  short_summary: [],
  empty_list_item: [],
  dup_in_list: [],
  tiny_list: [],
  missing_close: [],
};

function checkStr(slug, field, s) {
  if (typeof s !== "string") return;
  if (LATIN.test(s)) issues.english_words.push({slug, field, sample: s.slice(0, 80)});
  if (NBSP_LEADING.test(s)) issues.leading_ws.push({slug, field, sample: s.slice(0, 50)});
  if (NBSP_TRAILING.test(s)) issues.trailing_ws.push({slug, field, sample: s.slice(-50)});
  if (MD_WRAP.test(s)) issues.markdown_wrap.push({slug, field, sample: s.slice(0, 60)});
  if (INLINE_MD.test(s)) issues.inline_md.push({slug, field, sample: s.slice(0, 80)});
}

const cursor = db.medications.find(
  { enrichment: { $exists: true } },
  { _id: 0, slug: 1, enrichment: 1 },
);
let scanned = 0;
cursor.forEach(d => {
  scanned += 1;
  const e = d.enrichment || {};
  const slug = d.slug;

  // missing fields
  for (const k of ["summary", "indications", "contraindications", "how_to_take", "disclaimer"]) {
    const v = e[k];
    if (v === undefined || v === null || (Array.isArray(v) ? v.length === 0 : v === "")) {
      issues.missing_field.push({slug, field: k});
    }
  }

  if (typeof e.summary === "string") {
    checkStr(slug, "summary", e.summary);
    if (e.summary.trim().length < 30) issues.short_summary.push({slug, sample: e.summary});
  }

  for (const k of ["how_to_take", "disclaimer"]) {
    checkStr(slug, k, e[k]);
  }
  if (typeof e.how_to_take === "string" && !e.how_to_take.includes(CLOSER)) {
    issues.missing_close.push({slug, sample: e.how_to_take.slice(-80)});
  }

  for (const k of ["indications", "contraindications"]) {
    const arr = e[k];
    if (!Array.isArray(arr)) continue;
    const norm = [];
    arr.forEach((x, i) => {
      if (typeof x !== "string") return;
      checkStr(slug, `${k}[${i}]`, x);
      if (x.trim() === "") issues.empty_list_item.push({slug, field: k});
      norm.push(x.trim().toLowerCase());
    });
    if (arr.length < 2) issues.tiny_list.push({slug, field: k, n: arr.length});
    // duplicates
    const seen = new Set();
    for (const n of norm) {
      if (n && seen.has(n)) { issues.dup_in_list.push({slug, field: k, item: n.slice(0, 60)}); break; }
      seen.add(n);
    }
  }
});

print("scanned: " + scanned);
const summary = {};
for (const k of Object.keys(issues)) summary[k] = issues[k].length;
print("issue counts: " + JSON.stringify(summary, null, 2));

// dump first few examples per category
for (const k of Object.keys(issues)) {
  if (!issues[k].length) continue;
  print("--- " + k + " (showing up to 5) ---");
  issues[k].slice(0, 5).forEach(x => print("  " + JSON.stringify(x)));
}
