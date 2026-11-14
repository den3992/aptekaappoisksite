import { cache } from 'react';
import { fetchCategories, searchMeds } from '../api/client';
import { timedCache } from './timedCache';

// React cache shares the same result between generateMetadata and Page within
// one server request. Primitive arguments keep cities and pages separate.
export const getCategories = cache(city => fetchCategories(city));

const POPULAR_QUERIES = ['Парацетамол', 'Нурофен', 'Витамин D3', 'Омепразол', 'Кагоцел', 'Смекта'];
const loadPopularMeds = timedCache(async city => {
  // This block is optional; do not add the API client's 20s timeout to the
  // homepage's critical path when popular suggestions are unavailable.
  const signal = AbortSignal.timeout(3000);
  const results = await Promise.all(POPULAR_QUERIES.map(q =>
    searchMeds({ q, city, pageSize: 1, signal })
  ));
  const meds = results.flatMap(result => result.items.slice(0, 1));
  return [...new Map(meds.map(med => [med.slug, med])).values()];
}, 60_000);
export const getPopularMeds = cache(city => loadPopularMeds(city));

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
