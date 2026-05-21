// Direct string-replace for known stubborn artefacts that LLM keeps reproducing.
// Patterns observed: latin character clusters wedged inside Cyrillic words.

const FIXES = [
  // observed artefacts
  [/перipheral/gi, "периферическая"],
  [/Римеgepант/g, "Римегепант"],
  [/римеgepант/g, "римегепант"],
  [/nasal congestion/gi, "заложенность носа"],
  [/остраяrenal insufficiency/gi, "острая почечная недостаточность"],
  [/острая renal insufficiency/gi, "острая почечная недостаточность"],
  [/renal insufficiency/gi, "почечная недостаточность"],
  [/intravenously/gi, "внутривенно"],
  [/intramuscularly/gi, "внутримышечно"],
  [/intramuscular/gi, "внутримышечный"],
  [/intravenous/gi, "внутривенный"],
  [/subcutaneously/gi, "подкожно"],
  [/subcutaneous/gi, "подкожный"],
  [/hypersensitivity/gi, "повышенная чувствительность"],
  [/Гipersensitivity/gi, "Повышенная чувствительность"],
  [/aspergillosis/gi, "аспергиллёз"],
  [/electrolyte imbalance/gi, "нарушение электролитного баланса"],
  [/prolongation of QT interval/gi, "удлинение интервала QT"],
  [/abdominal cavity/gi, "брюшная полость"],
  [/cerebral/gi, "мозговое"],
  [/кардиогенShock/gi, "кардиогенный шок"],
  [/vestibular/gi, "вестибулярной"],
  [/pheochromocytoma/gi, "феохромоцитома"],
  // double-cap initial latin letter wedged in Cyrillic name beginning
  [/\bАmlodipin/g, "Амлодипин"],
  [/\bAmlodipin/g, "Амлодипин"],
  [/\bBisoprolol/g, "Бисопролол"],
  [/\bHydrogesterone/g, "дидрогестерон"],
  [/\bdi Hydrogesterone/gi, "дидрогестерон"],
  [/\batorvastatin\b/g, "аторвастатина"],
  [/\bloratadine\b/gi, "лоратадин"],
];

const cursor = db.medications.find(
  { enrichment: { $exists: true } },
  { _id: 0, slug: 1, enrichment: 1 },
);

let docsChanged = 0;
let fieldsChanged = 0;
const ops = [];

cursor.forEach(d => {
  const e = d.enrichment;
  let changed = false;
  const next = { ...e };

  function fixStr(s) {
    if (typeof s !== "string") return s;
    let r = s;
    for (const [re, rep] of FIXES) r = r.replace(re, rep);
    if (r !== s) fieldsChanged += 1;
    return r;
  }

  for (const k of ["summary", "how_to_take", "disclaimer"]) {
    if (typeof e[k] === "string") {
      const r = fixStr(e[k]);
      if (r !== e[k]) { next[k] = r; changed = true; }
    }
  }
  for (const k of ["indications", "contraindications"]) {
    if (Array.isArray(e[k])) {
      const r = e[k].map(fixStr);
      if (r.some((x, i) => x !== e[k][i])) { next[k] = r; changed = true; }
    }
  }
  if (changed) {
    docsChanged += 1;
    ops.push({ updateOne: { filter: { slug: d.slug }, update: { $set: { enrichment: next } } } });
  }
});

print("docs changed: " + docsChanged + ", field substitutions: " + fieldsChanged);
if (ops.length) {
  const res = db.medications.bulkWrite(ops, { ordered: false });
  print("matched=" + res.matchedCount + ", modified=" + res.modifiedCount);
}
