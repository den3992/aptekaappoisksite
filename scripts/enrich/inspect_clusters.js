// Inspect dedup clusters of the 100 just-enriched slugs.
const fs = require('fs');
const data = JSON.parse(fs.readFileSync('/tmp/enrichments.json', 'utf8'));
const slugs = data.map(d => d.slug);
print('input slugs: ' + slugs.length);

const docs = db.medications.find(
  { slug: { $in: slugs } },
  { _id: 0, slug: 1, dedup_key: 1, is_canonical: 1, canonical_slug: 1, name: 1, mnn: 1, form: 1, dosage: 1 },
).toArray();
print('matched: ' + docs.length);

const haveKey = docs.filter(d => d.dedup_key);
print('with dedup_key: ' + haveKey.length + ' / ' + docs.length);

const keys = [...new Set(haveKey.map(d => d.dedup_key))];
print('unique dedup_keys among 100: ' + keys.length);

const all = db.medications.countDocuments({ dedup_key: { $in: keys } });
print('total cards sharing those dedup_keys: ' + all);

const enrInCluster = db.medications.countDocuments({
  dedup_key: { $in: keys },
  enrichment: { $exists: true },
});
print('of those, already enriched: ' + enrInCluster);

print('--- 5 biggest clusters (cards sharing dedup_key with our 100) ---');
db.medications.aggregate([
  { $match: { dedup_key: { $in: keys } } },
  { $group: { _id: '$dedup_key', n: { $sum: 1 },
    samples: { $push: { slug: '$slug', man: '$manufacturer', dose: '$dosage', form: '$form', name: '$name' } } } },
  { $sort: { n: -1 } },
  { $limit: 5 },
]).forEach(d => {
  print('cluster size ' + d.n + ' (key ' + d._id + '):');
  d.samples.slice(0, 6).forEach(s => print('  - ' + s.name + ' ' + (s.dose||'') + ' ' + (s.form||'') + ' | ' + s.man + '  -> ' + s.slug));
});

print('--- how is_canonical splits among our 100 ---');
const can = docs.filter(d => d.is_canonical === true).length;
const noncan = docs.filter(d => d.is_canonical === false).length;
const undef = docs.filter(d => d.is_canonical === undefined).length;
print('canonical=true: ' + can + ', canonical=false: ' + noncan + ', undef: ' + undef);
