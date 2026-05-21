// Build /tmp/fix_groups.json for the 3 still-missing cards by slug.
const targets = [
  "gamamelis-virginiana-kalendula-officinalis-levomentol-cinka-oksid-eskulyus-gippokastanum",
  "leyprorelin-3-75-mg",
  "folievaya-kislota-1-mg",
];

// Find ALL un-enriched cards with the same MNN+form+dosage as any of these names
// (just in case slug differs). Simpler: fetch un-enriched and grep by MNN we know.

const groups = db.medications.aggregate([
  { $match: { enrichment: { $exists: false } } },
  { $group: {
      _id: { mnn: "$mnn", form: "$form", dosage: "$dosage" },
      all_slugs: { $addToSet: "$slug" },
  }},
  { $project: {
      _id: 0,
      mnn: "$_id.mnn", form: "$_id.form", dosage: "$_id.dosage",
      all_slugs: 1,
  }},
]).toArray();

print(JSON.stringify(groups));
