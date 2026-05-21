// A1: normalise how_to_take closing phrase across all enriched docs.
// Replace any variant of "определяются/определяется врачом" with the canonical
// "Точную дозировку и продолжительность курса определяет врач."

const VARIANTS = [
  /Точная дозировка и продолжительность курса определяются врачом\.?/g,
  /Точная дозировка и продолжительность курса определяется врачом\.?/g,
  /Tочную дозировку и продолжительность курса определяет врач\.?/g,  // latin T
];
const CANON = "Точную дозировку и продолжительность курса определяет врач.";

let fixed = 0;
const cursor = db.medications.find(
  { enrichment: { $exists: true }, "enrichment.how_to_take": { $exists: true } },
  { _id: 0, slug: 1, "enrichment.how_to_take": 1 },
);

const ops = [];
cursor.forEach(d => {
  let s = d.enrichment.how_to_take;
  if (typeof s !== "string") return;
  const orig = s;
  for (const re of VARIANTS) s = s.replace(re, CANON);
  if (s !== orig) {
    ops.push({ updateOne: { filter: { slug: d.slug }, update: { $set: { "enrichment.how_to_take": s } } } });
  }
});

print("docs needing how_to_take fix: " + ops.length);
if (ops.length) {
  const res = db.medications.bulkWrite(ops, { ordered: false });
  print("matched=" + res.matchedCount + ", modified=" + res.modifiedCount);
}
