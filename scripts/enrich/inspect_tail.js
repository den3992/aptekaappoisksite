// Inspect the remaining un-enriched tail: how many have full (mnn, form, dosage) keys?
const totalUnenriched = db.medications.countDocuments({ enrichment: { $exists: false } });
print("un-enriched total: " + totalUnenriched);

const buckets = {
  has_all_three: 0,
  no_mnn: 0,
  no_form: 0,
  no_dosage: 0,
  has_only_name: 0,
};

db.medications.find(
  { enrichment: { $exists: false } },
  { _id: 0, mnn: 1, form: 1, dosage: 1, name: 1 },
).forEach(d => {
  const has_mnn = !!d.mnn;
  const has_form = !!d.form;
  const has_dosage = !!d.dosage;
  if (has_mnn && has_form && has_dosage) buckets.has_all_three += 1;
  else if (!has_mnn && !has_form && !has_dosage) buckets.has_only_name += 1;
  else {
    if (!has_mnn) buckets.no_mnn += 1;
    if (!has_form) buckets.no_form += 1;
    if (!has_dosage) buckets.no_dosage += 1;
  }
});
print(JSON.stringify(buckets, null, 2));

// How many remaining groups with full keys?
const remGroups = db.medications.aggregate([
  { $match: {
      enrichment: { $exists: false },
      mnn: { $ne: null, $ne: "" },
      form: { $ne: null, $ne: "" },
      dosage: { $ne: null, $ne: "" },
  }},
  { $group: {
      _id: { mnn: "$mnn", form: "$form", dosage: "$dosage" },
      n: { $sum: 1 },
  }},
  { $count: "groups" },
]).toArray();
print("distinct remaining groups (full keys): " + (remGroups[0] ? remGroups[0].groups : 0));
