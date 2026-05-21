// Dedupe how_to_take closing phrase. If both an alternate phrase ("определяются/определяется")
// AND the canonical exist, drop the alternate. Also collapse two canonicals into one.

const CANON = "Точную дозировку и продолжительность курса определяет врач.";
const ALTS = [
  "Точная дозировка и продолжительность курса определяются врачом.",
  "Точная дозировка и продолжительность курса определяется врачом.",
  "Точная схема применения и продолжительность курса зависят от конкретного случая и определяются врачом.",
];

const cursor = db.medications.find(
  { enrichment: { $exists: true }, "enrichment.how_to_take": { $exists: true } },
  { _id: 0, slug: 1, "enrichment.how_to_take": 1 },
);

const ops = [];
cursor.forEach(d => {
  let s = d.enrichment.how_to_take;
  if (typeof s !== "string") return;
  const orig = s;

  // Drop alternates if canon already present
  if (s.includes(CANON)) {
    for (const a of ALTS) {
      while (s.includes(a)) s = s.replace(a, "");
    }
  }
  // Collapse repeated canonicals
  const idx = s.indexOf(CANON);
  if (idx >= 0) {
    const second = s.indexOf(CANON, idx + CANON.length);
    if (second >= 0) {
      s = s.slice(0, idx + CANON.length) + s.slice(second + CANON.length);
    }
  }
  // Tidy whitespace
  s = s.replace(/\s+/g, " ").replace(/\s+\./g, ".").trim();

  if (s !== orig) {
    ops.push({ updateOne: { filter: { slug: d.slug }, update: { $set: { "enrichment.how_to_take": s } } } });
  }
});

print("ops: " + ops.length);
if (ops.length) {
  const res = db.medications.bulkWrite(ops, { ordered: false });
  print("matched=" + res.matchedCount + ", modified=" + res.modifiedCount);
}
