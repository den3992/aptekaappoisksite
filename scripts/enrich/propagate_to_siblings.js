// Step 1: propagate `enrichment` from the 100 just-enriched canonical cards
// to all non-canonical cards that share the same dedup_key (i.e. exactly the
// same drug, just a slightly different manufacturer-name spelling).

const fs = require('fs');
const data = JSON.parse(fs.readFileSync('/tmp/enrichments.json', 'utf8'));
const slugs = data.map(d => d.slug);

// Build map: dedup_key -> enrichment (from the canonical cards we updated)
const canonicals = db.medications.find(
  { slug: { $in: slugs } },
  { _id: 0, slug: 1, dedup_key: 1, enrichment: 1 },
).toArray();

const byKey = {};
for (const c of canonicals) {
  if (c.dedup_key && c.enrichment) byKey[c.dedup_key] = c.enrichment;
}
print('dedup_keys with enrichment: ' + Object.keys(byKey).length);

// Find sibling cards (same dedup_key, different slug, no enrichment yet)
const targets = db.medications.find({
  dedup_key: { $in: Object.keys(byKey) },
  slug: { $nin: slugs },
  enrichment: { $exists: false },
}, { _id: 0, slug: 1, dedup_key: 1, name: 1, manufacturer: 1 }).toArray();
print('non-canonical siblings to enrich: ' + targets.length);

if (targets.length) {
  const ops = targets.map(t => ({
    updateOne: {
      filter: { slug: t.slug },
      update: { $set: { enrichment: byKey[t.dedup_key] } },
    },
  }));
  const res = db.medications.bulkWrite(ops, { ordered: false });
  print('matched=' + res.matchedCount + ', modified=' + res.modifiedCount);
}

print('total enriched now: ' + db.medications.countDocuments({ enrichment: { $exists: true } }));
