// Step 2b: pick up to N groups (MNN+form+dosage) where no card is enriched yet.
// Now WITHOUT the popular-MNN restriction — order purely by group size.
const TARGET_GROUPS = 3000;  // > 2614, will get all remaining

const groups = db.medications.aggregate([
  { $match: {
      mnn: { $ne: null, $ne: "" },
      form: { $ne: null, $ne: "" },
      dosage: { $ne: null, $ne: "" },
  }},
  { $group: {
      _id: { mnn: '$mnn', form: '$form', dosage: '$dosage' },
      total: { $sum: 1 },
      enriched: { $sum: { $cond: [{ $ifNull: ['$enrichment', false] }, 1, 0] } },
      all_slugs: { $push: '$slug' },
  }},
  { $match: { enriched: 0 } },
  { $sort: { total: -1, '_id.mnn': 1 } },
  { $limit: TARGET_GROUPS },
  { $project: {
      _id: 0,
      mnn: '$_id.mnn', form: '$_id.form', dosage: '$_id.dosage',
      total: 1, all_slugs: 1,
  }},
]).toArray();

print(JSON.stringify(groups));
