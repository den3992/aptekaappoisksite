// Fix double space artefacts (collapse multiple spaces to one).
const cursor = db.medications.find(
  { enrichment: { $exists: true } },
  { _id: 0, slug: 1, enrichment: 1 },
);
const ops = [];
cursor.forEach(d => {
  const e = d.enrichment;
  let changed = false;
  const next = { ...e };

  function norm(s) {
    if (typeof s !== "string") return s;
    const r = s.replace(/  +/g, " ");
    if (r !== s) changed = true;
    return r;
  }

  for (const k of ["summary", "how_to_take", "disclaimer"]) {
    if (typeof e[k] === "string") next[k] = norm(e[k]);
  }
  for (const k of ["indications", "contraindications"]) {
    if (Array.isArray(e[k])) next[k] = e[k].map(norm);
  }
  if (changed) ops.push({ updateOne: { filter: { slug: d.slug }, update: { $set: { enrichment: next } } } });
});
print("ops: " + ops.length);
if (ops.length) {
  const res = db.medications.bulkWrite(ops, { ordered: false });
  print("matched=" + res.matchedCount + ", modified=" + res.modifiedCount);
}
