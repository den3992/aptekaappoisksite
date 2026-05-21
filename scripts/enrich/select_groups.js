// Step 2a: pick top-100 (MNN, form, dosage) groups where no card is enriched yet.
// One LLM call per group will then enrich ALL cards in that group (typically 3-15).

const POPULAR_MNN = [
  "ПАРАЦЕТАМОЛ","ИБУПРОФЕН","АЦЕТИЛСАЛИЦИЛОВАЯ КИСЛОТА","ОМЕПРАЗОЛ",
  "ЛОРАТАДИН","ЦЕТИРИЗИН","ХЛОРОПИРАМИН","ДРОТАВЕРИН",
  "МЕТАМИЗОЛ НАТРИЯ","КЕТОПРОФЕН","ЛОПЕРАМИД","СМЕКТИТ ДИОКТАЭДРИЧЕСКИЙ",
  "АМБРОКСОЛ","БРОМГЕКСИН","АЦЕТИЛЦИСТЕИН",
  "АМОКСИЦИЛЛИН","АЗИТРОМИЦИН","ЦИПРОФЛОКСАЦИН","МЕТРОНИДАЗОЛ","ФЛУКОНАЗОЛ",
  "КОЛЕКАЛЬЦИФЕРОЛ","АСКОРБИНОВАЯ КИСЛОТА","МАГНИЯ ЛАКТАТ","МАГНИЯ ЦИТРАТ","МЕЛЬДОНИЙ",
  "ФУРОСЕМИД","ЭНАЛАПРИЛ","ЛОЗАРТАН","АМЛОДИПИН","БИСОПРОЛОЛ","МЕТОПРОЛОЛ",
  "ГЛИЦИН","МЕЛАТОНИН","НИМЕСУЛИД","ДИКЛОФЕНАК",
  "АНАСТРОЗОЛ","ТАМОКСИФЕН","ИНСУЛИН ГЛАРГИН","МЕТФОРМИН",
  "АМИОДАРОН","ВАРФАРИН","ГЕПАРИН НАТРИЯ","СУМАТРИПТАН","БЕТАГИСТИН",
  "АТОРВАСТАТИН","РОЗУВАСТАТИН","СИМВАСТАТИН","КЕТОТИФЕН","ДЕЗЛОРАТАДИН",
  "ИВЕРМЕКТИН","ОСЕЛЬТАМИВИР","АЦИКЛОВИР","УМИФЕНОВИР","РИБАВИРИН",
  "ЭСОМЕПРАЗОЛ","ПАНТОПРАЗОЛ","ФАМОТИДИН","ДОМПЕРИДОН","МЕТОКЛОПРАМИД",
  "АТРОПИН","ПЛАТИФИЛЛИН","СПИРОНОЛАКТОН","ИНДАПАМИД",
];

const groups = db.medications.aggregate([
  { $match: {
      mnn: { $in: POPULAR_MNN, $ne: null },
      form: { $ne: null, $ne: "" },
      dosage: { $ne: null, $ne: "" },
  }},
  { $group: {
      _id: { mnn: '$mnn', form: '$form', dosage: '$dosage' },
      total: { $sum: 1 },
      enriched: { $sum: { $cond: [{ $ifNull: ['$enrichment', false] }, 1, 0] } },
      sample_slug: { $first: '$slug' },
      sample_name: { $first: '$name' },
      sample_manufacturer: { $first: '$manufacturer' },
      all_slugs: { $push: '$slug' },
  }},
  { $match: { enriched: 0 } },           // not yet enriched at all
  { $sort: { total: -1, '_id.mnn': 1 } }, // largest groups first
  { $limit: 100 },
  { $project: {
      _id: 0,
      mnn: '$_id.mnn', form: '$_id.form', dosage: '$_id.dosage',
      total: 1,
      sample_slug: 1, sample_name: 1, sample_manufacturer: 1,
      all_slugs: 1,
  }},
]).toArray();

print(JSON.stringify(groups));
