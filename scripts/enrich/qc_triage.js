// Triage of `english_words`: classify each occurrence so we know what to fix.
//   "safe"   - looks like a scientific marker that should stay (HER2, IgG, BCR-ABL, etc.)
//   "homeo"  - homeopathy uses transliterated Latin; tolerate
//   "bad"    - real English words/phrases that should be retranslated

const SAFE_PATTERNS = [
  /\bHER\d\b/i, /\bEGFR\b/, /\bALK\b/, /\bBCR-?ABL\b/i,
  /\bROS1\b/, /\bKRAS\b/, /\bBRAF\b/, /\bPI3K\b/, /\bMTOR\b/,
  /\bMEK\b/, /\bRAS\b/, /\bAT1\b/, /\bRAS\b/, /\bIgG\b/, /\bIgM\b/, /\bIgE\b/, /\bIgA\b/,
  /\bIL-?\d+\b/, /\bTNF\b/, /\bVEGF\b/, /\bPDGF\b/, /\bIGF-?\d?\b/,
  /\bCRP\b/, /\bPSA\b/, /\bHbA1c\b/i, /\bLDL\b/, /\bHDL\b/, /\bBMI\b/,
  /\bSARS-?CoV-?2\b/i, /\bCOVID-?19\b/i, /\bHIV\b/, /\bHBV\b/, /\bHCV\b/,
  /\bATP\b/, /\bDNA\b/, /\bRNA\b/, /\bCD\d+\b/,
  /\bICU\b/, /\bATC\b/, /\bGABA\b/i, /\bAUC\b/, /\bAUDIT\b/,
  /\b[ABCDEFG]\d{1,3}\b/,                       // ATC codes / drug codes
  /\b[A-Z][a-z]+um\s+[a-z]+/,                   // Latin "Aurum metallicum" style
  /\b[A-Z][a-z]+a\s+[a-z]+/,
];
const HOMEO_KEYWORDS = /гомеопат|гомеопатич/i;

const SAFE_TERMS = new Set([
  "her2","her3","her4","egfr","alk","bcrabl","ros1","kras","braf","pi3k","mtor","mek","ras","at1",
  "igg","igm","ige","iga","tnf","vegf","pdgf","igf","crp","psa","ldl","hdl","bmi","atp","dna","rna",
  "hiv","hbv","hcv","icu","atc","gaba","auc","sars","sarscov","sarscov2","covid","covid19",
  "ph","mr","ct","mri","ecg","emg","auc","aucss","auch","aucs",
  // microorganisms (used as scientific names in indications)
  "helicobacter","pylori","escherichia","coli","staphylococcus","aureus",
  "streptococcus","pneumoniae","pyogenes","lactobacillus","bifidobacterium",
  "candida","albicans","aspergillus","mycobacterium","tuberculosis",
  "pseudomonas","aeruginosa","klebsiella","neisseria","gonorrhoeae",
  "chlamydia","trachomatis","mycoplasma","ureaplasma","trichomonas",
  "treponema","pallidum","plasmodium","giardia","amoeba","entamoeba",
  "haemophilus","influenzae","bordetella","pertussis","corynebacterium",
  "diphtheriae","clostridium","tetani","botulinum","yersinia","shigella",
  "salmonella","typhi","vibrio","cholerae","brucella","listeria",
  "monocytogenes","legionella","pneumophila","borrelia","burgdorferi",
  // blood group / immunology markers
  "rh","rho","rhd","rhc","rhe","ab0","abo",
  // common scientific suffixes / receptors / cytokines
  "s100","s-100","no","nos","enos","inos","ace","ace2","ngf","bdnf",
  "fsh","lh","tsh","ctk","ck","mb","ldh","ast","alt","ggt","alp",
  "wbc","rbc","plt","hgb","hb","mch","mcv",
  // common drug class abbreviations
  "nsaid","ssri","snri","tca","maoi","arb","ace","sglt2","glp","glp1",
  // radiopharmaceutical isotopes
  "tc","mtc","99mtc","99m","tl","ga","in","f","fdg","11c","18f","123i","131i","177lu",
]);

function isSafeMarker(token) {
  const t = token.toLowerCase().replace(/[-\.]/g, "");
  if (SAFE_TERMS.has(t)) return true;
  // very short markers (<=3 letters all caps) and tokens with digits
  if (/^[A-Z]+\d+$/.test(token) || /^[A-Z]{2,5}$/.test(token)) return true;
  if (/\d/.test(token)) return true;
  return false;
}

function classify(text) {
  const tokens = text.match(/[A-Za-z][A-Za-z\-]+/g) || [];
  let hasSafe = false, hasBad = false;
  for (const t of tokens) {
    if (isSafeMarker(t)) hasSafe = true;
    else if (t.length >= 3) hasBad = true;
  }
  if (hasBad) return "bad";
  if (hasSafe) return "safe";
  return "safe";
}

const cursor = db.medications.find(
  { enrichment: { $exists: true } },
  { _id: 0, slug: 1, enrichment: 1, form: 1 },
);

const bad = [];          // really need fixing
const safeOnly = [];     // tolerate, no action

cursor.forEach(d => {
  const e = d.enrichment || {};
  const form = d.form || "";
  const isHomeo = HOMEO_KEYWORDS.test(form) || HOMEO_KEYWORDS.test(e.summary || "");
  const fields = [];
  for (const k of ["summary", "how_to_take", "disclaimer"]) {
    if (typeof e[k] === "string" && /[A-Za-z]/.test(e[k])) fields.push({k, v: e[k]});
  }
  for (const k of ["indications", "contraindications"]) {
    if (Array.isArray(e[k])) {
      e[k].forEach((x, i) => {
        if (typeof x === "string" && /[A-Za-z]/.test(x)) fields.push({k: `${k}[${i}]`, v: x});
      });
    }
  }
  if (!fields.length) return;
  let anyBad = false;
  const samples = [];
  for (const f of fields) {
    const cls = classify(f.v);
    if (cls === "bad" && !isHomeo) {
      anyBad = true;
      samples.push({field: f.k, sample: f.v.slice(0, 80)});
    }
  }
  if (anyBad) bad.push({slug: d.slug, isHomeo, samples});
  else safeOnly.push({slug: d.slug, samples: fields.slice(0,1).map(f => ({field: f.k, sample: f.v.slice(0,60)}))});
});

print("BAD (re-gen candidates): " + bad.length);
print("SAFE-only (markers like HER2/IgG/Latin homeo): " + safeOnly.length);

print("\n--- 20 BAD samples ---");
bad.slice(0, 20).forEach(b => print("  " + b.slug + " | " + b.samples[0].field + " | " + b.samples[0].sample));

print("\n--- 10 SAFE samples (no action) ---");
safeOnly.slice(0, 10).forEach(s => print("  " + s.slug + " | " + s.samples[0].field + " | " + s.samples[0].sample));

// dump full bad list
const fs = require("fs");
fs.writeFileSync("/tmp/bad_slugs.json", JSON.stringify(bad.map(b => b.slug), null, 2));
print("\nWrote " + bad.length + " bad slugs to /tmp/bad_slugs.json");
