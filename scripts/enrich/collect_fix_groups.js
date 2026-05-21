// Collect ALL slugs that need re-generation, dedupe by (mnn, form, dosage),
// return distinct groups so the LLM-pass enriches each group exactly once.

const fs = require("fs");
const badSlugs = JSON.parse(fs.readFileSync("/tmp/bad_slugs.json", "utf8"));

// Add A2: leading whitespace in indications/contraindications (3 docs)
const wsCursor = db.medications.find({
  enrichment: { $exists: true },
  $or: [
    { "enrichment.indications":      { $elemMatch: { $regex: "^\\s" } } },
    { "enrichment.contraindications":{ $elemMatch: { $regex: "^\\s" } } },
  ],
}, { _id: 0, slug: 1 }).toArray();
const wsSlugs = wsCursor.map(d => d.slug);

// Add A2: missing contraindications field
const missCursor = db.medications.find({
  enrichment: { $exists: true },
  $or: [
    { "enrichment.contraindications": { $exists: false } },
    { "enrichment.contraindications": [] },
    { "enrichment.contraindications": null },
  ],
}, { _id: 0, slug: 1 }).toArray();
const missSlugs = missCursor.map(d => d.slug);

const allSlugs = [...new Set([...badSlugs, ...wsSlugs, ...missSlugs])];
print("bad slugs (english):   " + badSlugs.length);
print("leading-ws slugs:      " + wsSlugs.length);
print("missing-field slugs:   " + missSlugs.length);
print("unique union:          " + allSlugs.length);

// Group into (mnn, form, dosage) keys
const groups = db.medications.aggregate([
  { $match: { slug: { $in: allSlugs } } },
  { $group: {
      _id: { mnn: "$mnn", form: "$form", dosage: "$dosage" },
      slugs_in_db: { $addToSet: "$slug" },          // bad slugs from this group
  }},
  // Now expand each group to ALL siblings in the DB with the same (mnn, form, dosage)
  { $lookup: {
      from: "medications",
      let: { gmnn: "$_id.mnn", gform: "$_id.form", gdose: "$_id.dosage" },
      pipeline: [
        { $match: { $expr: { $and: [
          { $eq: ["$mnn", "$$gmnn"] },
          { $eq: ["$form", "$$gform"] },
          { $eq: ["$dosage", "$$gdose"] },
        ]}}},
        { $project: { _id: 0, slug: 1 } },
      ],
      as: "all_siblings",
  }},
  { $project: {
      _id: 0,
      mnn: "$_id.mnn", form: "$_id.form", dosage: "$_id.dosage",
      all_slugs: { $map: { input: "$all_siblings", as: "s", in: "$$s.slug" } },
  }},
]).toArray();

print("distinct (mnn,form,dosage) groups: " + groups.length);
print("total sibling cards to update:     " + groups.reduce((s,g) => s + g.all_slugs.length, 0));

fs.writeFileSync("/tmp/fix_groups.json", JSON.stringify(groups, null, 2));
print("Wrote /tmp/fix_groups.json");
