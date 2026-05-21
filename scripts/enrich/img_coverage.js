// Manufacturer coverage analysis: for each manufacturer, how many SKUs have image_url already?
const stats = db.medications.aggregate([
  { $group: {
      _id: "$manufacturer",
      total: { $sum: 1 },
      with_image: { $sum: { $cond: [{ $and: [
        { $ifNull: ["$image_url", false] },
        { $ne: ["$image_url", ""] },
      ]}, 1, 0]}},
  }},
  { $addFields: {
      missing: { $subtract: ["$total", "$with_image"] },
      coverage_pct: { $multiply: [{ $divide: ["$with_image", "$total"] }, 100] },
  }},
  { $sort: { missing: -1 } },
  { $limit: 40 },
]).toArray();

print("Top-40 manufacturers by 'missing image' count:");
print("missing | total | cov% | manufacturer");
stats.forEach(s => {
  print(
    String(s.missing).padStart(4) + " | " +
    String(s.total).padStart(5) + " | " +
    String(Math.round(s.coverage_pct)).padStart(3) + "% | " +
    (s._id || "(empty)")
  );
});
