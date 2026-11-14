import { cache } from 'react';
import { fetchCategories, searchMeds } from '../api/client';

// React cache shares the same result between generateMetadata and Page within
// one server request. Primitive arguments keep cities and pages separate.
export const getCategories = cache(city => fetchCategories(city));

export const getCatalog = cache((city, page) =>
  searchMeds({ city, page, pageSize: 48 })
);

export const getCategory = cache(async (city, slug, page) => {
  const [categories, data] = await Promise.all([
    getCategories(city),
    searchMeds({ category: slug, city, page, pageSize: 24 }),
  ]);
  const category = categories.find(item => item.slug === slug);
  // The search response supplies both the displayed list and its total. A
  // briefly cached category count must not contradict this fresh result.
  return { category: category ? { ...category, count: data.total } : null, data };
});
