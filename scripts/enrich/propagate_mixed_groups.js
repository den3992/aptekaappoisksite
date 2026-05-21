// Propagate enrichment to un-enriched cards whose siblings (same mnn/form/dosage) ARE already enriched.
// Speed-up: iterate groups that contain at least one enriched + one un-enriched card.

const groups = db.medications.aggregate([
  { $match: { mnn: { $ne: null, $ne: "" }, form: { $ne: null, $ne: "" }, dosage: { $ne: null, $ne: "" } } },
  { $group: {
      _id: { mnn: "$mnn", form: "$form", dosage: "$dosage" },
      enriched_doc: { $first: { $cond: [{ $ifNull: ["$enrichment", false] }, { slug: "$slug", enrichment: "$enrichment" }, null] } },
      // collect first enriched doc
      enriched_sample: { $max: { $cond: [{ $ifNull: ["$enrichment", false] }, "$slug", null] } },
      un_enriched_slugs: { $addToSet: { $cond: [{ $ifNull: ["$enrichment", false] }, null, "$slug"] } },
      enriched_count: { $sum: { $cond: [{ $ifNull: ["$enrichment", false] }, 1, 0] } },
      total: { $sum: 1 },
  }},
  { $match: {
      enriched_count: { $gt: 0 },                  // group has at least one enriched
      $expr: { $lt: ["$enriched_count", "$total"] },  // ...and at least one un-enriched
  }},
  // we'll fetch the actual enrichment doc per group separately
  { $project: { _id: 0, mnn: "$_id.mnn", form: "$_id.form", dosage: "$_id.dosage", un_enriched_slugs: 1 } },
]).toArray();

print("mixed groups to propagate: " + groups.length);

let totalApplied = 0;
let processed = 0;
for (const g of groups) {
  // get an enriched sample from the same group
  const sample = db.medications.findOne(
    { mnn: g.mnn, form: g.form, dosage: g.dosage, enrichment: { $exists: true } },
    { _id: 0, enrichment: 1 },
  );
  if (!sample || !sample.enrichment) continue;
  const slugs = (g.un_enriched_slugs || []).filter(Boolean);
  if (!slugs.length) continue;
  const res = db.medications.updateMany(
    { slug: { $in: slugs }, enrichment: { $exists: false } },
    { $set: { enrichment: sample.enrichment } },
  );
  totalApplied += res.modifiedCount;
  processed += 1;
  if (processed % 100 === 0) print("...processed " + processed + " groups, applied " + totalApplied);
}
print("done. Total cards enriched via propagation: " + totalApplied);
print("total enriched now: " + db.medications.countDocuments({ enrichment: { $exists: true } }));
