// Deep QC scan for enrichment quality. Catches subtler artefacts than qc_scan.js.
//
// Categories:
//  - double_space, multi_punct, weird_quotes
//  - trailing_punct_missing       (summary doesn't end with . or ! or ?)
//  - placeholder                  ("информация уточняется", "TBD", "TODO")
//  - escape_sequence              ("\\n", "\\t", "\\u00xx" literal)
//  - markdown_list_marker         (lines starting with "- ", "* ", "1. ")
//  - numbered_in_list             (list item starts with "1.", "2.", etc.)
//  - repeated_word                (same word twice in a row)
//  - all_caps_word                (any word in ALL CAPS Cyrillic, suspect)
//  - very_short_item              (indications/contraindications item shorter than 5 chars)
//  - very_long_item               (list item longer than 150 chars)
//  - duplicate_across_fields      (indication == contraindication)
//  - same_summary                 (>50 docs share same summary -> generic boilerplate)
//  - same_indications             (>50 docs share exact indications list)
//  - missing_period_in_how        (how_to_take doesn't end with ".")
//  - emoji_or_special             (emoji or unusual unicode block)
//  - control_chars                (\r, \x00-\x1f except newline)

const issues = {};
function add(cat, payload){ (issues[cat] = issues[cat]||[]).push(payload); }

const CYR_UC_WORD = /\b[А-ЯЁ]{4,}\b/;          // 4+ Cyrillic uppercase letters in a row
const PLACEHOLDER = /(информация уточняется|TBD|TODO|N\/A|n\/a|<...>|\[\s*placeholder\s*\])/i;
const ESCAPE_SEQ = /\\n|\\t|\\r|\\u00|\\x[0-9a-f]/i;
const MARKDOWN_LIST = /(^|\n)\s*[-*]\s+/;
const NUMBERED_ITEM = /^\s*\d+\s*[\.\)]\s+/;
const REPEATED_WORD = /\b([а-яёА-ЯЁ]+)\s+\1\b/i;
const DOUBLE_SPACE = /  +/;
const MULTI_PUNCT = /[\.,!?;:]{2,}/;
const CONTROL = /[\x00-\x08\x0b\x0c\x0e-\x1f]/;
const EMOJI = /[\u{1f000}-\u{1ffff}\u{2600}-\u{27bf}]/u;
const WEIRD_QUOTES = /[«»„""''‚]{3,}/;          // 3+ quotes in a row

function checkStr(slug, field, s){
  if (typeof s !== "string") return;
  if (DOUBLE_SPACE.test(s)) add("double_space",  {slug, field, sample: s.match(DOUBLE_SPACE.source)? s.slice(0,80):s.slice(0,80)});
  if (MULTI_PUNCT.test(s))  add("multi_punct",   {slug, field, sample: s.slice(0,80)});
  if (PLACEHOLDER.test(s))  add("placeholder",   {slug, field, sample: s.slice(0,120)});
  if (ESCAPE_SEQ.test(s))   add("escape_sequence",{slug, field, sample: s.slice(0,80)});
  if (MARKDOWN_LIST.test(s))add("markdown_list_marker", {slug, field, sample: s.slice(0,80)});
  if (REPEATED_WORD.test(s))add("repeated_word", {slug, field, sample: (s.match(REPEATED_WORD)||[""])[0]});
  if (CONTROL.test(s))      add("control_chars", {slug, field});
  if (EMOJI.test(s))        add("emoji_or_special", {slug, field});
  if (WEIRD_QUOTES.test(s)) add("weird_quotes",  {slug, field, sample: s.slice(0,80)});
  if (CYR_UC_WORD.test(s))  add("all_caps_word", {slug, field, sample: (s.match(CYR_UC_WORD)||[""])[0]});
}

const summarySig = new Map();          // text -> count
const indicSig = new Map();            // JSON string -> count

const cursor = db.medications.find({}, { _id: 0, slug: 1, enrichment: 1 });
let scanned = 0;
cursor.forEach(d => {
  scanned += 1;
  const e = d.enrichment || {};
  const slug = d.slug;

  for (const k of ["summary","how_to_take","disclaimer"]) checkStr(slug, k, e[k]);

  // summary end-of-sentence
  if (typeof e.summary === "string" && !/[\.!?]\s*$/.test(e.summary)) {
    add("trailing_punct_missing", {slug, sample: e.summary.slice(-50)});
  }
  if (typeof e.how_to_take === "string" && !e.how_to_take.endsWith(".")) {
    add("missing_period_in_how", {slug, sample: e.how_to_take.slice(-50)});
  }

  // summary duplicates -> generic boilerplate
  if (typeof e.summary === "string") {
    summarySig.set(e.summary, (summarySig.get(e.summary) || 0) + 1);
  }
  if (Array.isArray(e.indications)) {
    const sig = JSON.stringify(e.indications);
    indicSig.set(sig, (indicSig.get(sig) || 0) + 1);
  }

  for (const k of ["indications","contraindications"]) {
    const arr = e[k];
    if (!Array.isArray(arr)) continue;
    for (let i=0; i<arr.length; i++){
      const x = arr[i];
      if (typeof x !== "string") continue;
      checkStr(slug, `${k}[${i}]`, x);
      if (NUMBERED_ITEM.test(x)) add("numbered_in_list", {slug, field: `${k}[${i}]`, sample: x.slice(0,60)});
      if (x.length < 5)  add("very_short_item", {slug, field: `${k}[${i}]`, sample: x});
      if (x.length > 150) add("very_long_item",  {slug, field: `${k}[${i}]`, sample: x.slice(0,80)+"…"});
    }
  }

  // cross-field duplication
  if (Array.isArray(e.indications) && Array.isArray(e.contraindications)) {
    const setC = new Set(e.contraindications.map(s => (s||"").trim().toLowerCase()));
    for (const ind of e.indications){
      const t = (ind||"").trim().toLowerCase();
      if (t && setC.has(t)) {
        add("duplicate_across_fields", {slug, sample: ind});
        break;
      }
    }
  }
});

// post-process aggregate signals
for (const [text, count] of summarySig.entries()){
  if (count >= 50) add("same_summary", {count, sample: text.slice(0, 100)});
}
for (const [sig, count] of indicSig.entries()){
  if (count >= 50) add("same_indications", {count, sample: sig.slice(0, 120)});
}

print("scanned: " + scanned);
const summary = {};
const keys = Object.keys(issues).sort();
for (const k of keys) summary[k] = issues[k].length;
print("issue counts: " + JSON.stringify(summary, null, 2));

// Show 3-5 examples per non-empty bucket
for (const k of keys){
  const arr = issues[k];
  if (!arr || !arr.length) continue;
  print("\n--- " + k + " (" + arr.length + ") ---");
  arr.slice(0, 5).forEach(x => print("  " + JSON.stringify(x)));
}
