// Apply medication enrichments produced by /app/enrich/run_enrich.py.
// Reads /tmp/enrichments.json (uploaded), bulk-updates `enrichment` field.

const fs = require('fs');
const data = JSON.parse(fs.readFileSync('/tmp/enrichments.json', 'utf8'));

let ops = data.map(d => ({
  updateOne: {
    filter: { slug: d.slug },
    update: { $set: { enrichment: d.enrichment } },
  },
}));

const res = db.medications.bulkWrite(ops, { ordered: false });
print(JSON.stringify({
  matched: res.matchedCount,
  modified: res.modifiedCount,
  upserted: res.upsertedCount,
  requested: data.length,
}));

// Quick sanity check
const sample = db.medications.findOne(
  { slug: data[0].slug },
  { _id: 0, slug: 1, name: 1, 'enrichment.summary': 1, 'enrichment.model': 1 },
);
print('SAMPLE: ' + JSON.stringify(sample));
