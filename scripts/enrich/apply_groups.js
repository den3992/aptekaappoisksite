// Apply group-based enrichment: each entry has multiple slugs sharing the same enrichment.
const fs = require('fs');
const data = JSON.parse(fs.readFileSync('/tmp/group_updates.json', 'utf8'));

let ops = [];
for (const item of data) {
  for (const slug of item.slugs) {
    ops.push({
      updateOne: {
        filter: { slug: slug, enrichment: { $exists: false } },  // safety: don't overwrite
        update: { $set: { enrichment: item.enrichment } },
      },
    });
  }
}
print('total ops to send: ' + ops.length);

const res = db.medications.bulkWrite(ops, { ordered: false });
print(JSON.stringify({
  matched: res.matchedCount,
  modified: res.modifiedCount,
  requested: ops.length,
}));

print('total enriched now: ' + db.medications.countDocuments({ enrichment: { $exists: true } }));
