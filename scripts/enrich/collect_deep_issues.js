// Collect slugs needing re-generation (placeholder + duplicate_across_fields)
// and double-space slugs that need a string-fix.
const fs = require("fs");

const PLACEHOLDER = /(информация уточняется|TBD|TODO|N\/A|n\/a|<...>|\[\s*placeholder\s*\])/i;
const DOUBLE_SPACE = /  +/;

const placeholderSlugs = new Set();
const dupSlugs = new Set();
const doubleSpaceSlugs = new Set();

db.medications.find(
  { enrichment: { $exists: true } },
  { _id: 0, slug: 1, enrichment: 1 },
).forEach(d => {
  const e = d.enrichment || {};
  const slug = d.slug;

  for (const k of ["summary","how_to_take","disclaimer"]) {
    const v = e[k];
    if (typeof v === "string") {
      if (PLACEHOLDER.test(v)) placeholderSlugs.add(slug);
      if (DOUBLE_SPACE.test(v)) doubleSpaceSlugs.add(slug);
    }
  }
  for (const k of ["indications","contraindications"]) {
    if (!Array.isArray(e[k])) continue;
    for (const x of e[k]) {
      if (typeof x === "string") {
        if (PLACEHOLDER.test(x)) placeholderSlugs.add(slug);
        if (DOUBLE_SPACE.test(x)) doubleSpaceSlugs.add(slug);
      }
    }
  }

  // cross-field duplicate
  if (Array.isArray(e.indications) && Array.isArray(e.contraindications)) {
    const setC = new Set(e.contraindications.map(s => (s||"").trim().toLowerCase()));
    for (const ind of e.indications){
      const t = (ind||"").trim().toLowerCase();
      if (t && setC.has(t)) { dupSlugs.add(slug); break; }
    }
  }
});

const regenUnion = new Set([...placeholderSlugs, ...dupSlugs]);
print("placeholder slugs:      " + placeholderSlugs.size);
print("duplicate_across slugs: " + dupSlugs.size);
print("double-space slugs:     " + doubleSpaceSlugs.size);
print("regen union (placeholder+dup): " + regenUnion.size);

fs.writeFileSync("/tmp/bad_slugs.json", JSON.stringify([...regenUnion], null, 2));
fs.writeFileSync("/tmp/double_space_slugs.json", JSON.stringify([...doubleSpaceSlugs], null, 2));
print("Wrote /tmp/bad_slugs.json and /tmp/double_space_slugs.json");
