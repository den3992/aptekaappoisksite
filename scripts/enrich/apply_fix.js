// Apply fix: overwrite existing enrichment (UNLIKE apply_groups.js which had a $exists:false guard).
const fs = require('fs');
const data = JSON.parse(fs.readFileSync('/tmp/fix_updates.json', 'utf8'));

let ops = [];
for (const item of data) {
  for (const slug of item.slugs) {
    ops.push({
      updateOne: {
        filter: { slug: slug },
        update: { $set: { enrichment: item.enrichment } },  // overwrite
      },
    });
  }
}
print('total ops: ' + ops.length);

const res = db.medications.bulkWrite(ops, { ordered: false });
print(JSON.stringify({ matched: res.matchedCount, modified: res.modifiedCount }));
print('enriched now: ' + db.medications.countDocuments({ enrichment: { $exists: true } }));
