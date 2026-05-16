// Centralized API client with helpers backed by FastAPI catalog endpoints.
// Replaces the static `mock.js` data source.
import axios from 'axios';

export const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const http = axios.create({
  baseURL: API,
  timeout: 20000,
});

// In-memory caches for static lookups (cities, categories) so we don't hit
// the backend on every page navigation.
let _categoriesCache = null;
let _citiesCache = null;

export async function fetchCities() {
  if (_citiesCache) return _citiesCache;
  const { data } = await http.get('/cities');
  _citiesCache = data;
  return data;
}

export async function fetchCategories() {
  if (_categoriesCache) return _categoriesCache;
  const { data } = await http.get('/categories');
  _categoriesCache = data;
  return data;
}

export async function fetchPharmacies(city = 'msk') {
  const { data } = await http.get('/pharmacies', { params: { city } });
  return data;
}

export async function fetchPharmacy(id) {
  const { data } = await http.get(`/pharmacies/${id}`);
  return data;
}

export async function searchMeds({ q, category, rx, prefix, page = 1, pageSize = 24 } = {}) {
  const params = { page, page_size: pageSize };
  if (q) params.q = q;
  if (category) params.category = category;
  if (rx !== undefined) params.rx = rx;
  if (prefix) params.prefix = prefix;
  const { data } = await http.get('/search', { params });
  return data;
}

export async function suggestMeds(q, limit = 8) {
  if (!q || q.trim().length < 2) return [];
  const { data } = await http.get('/search/suggest', { params: { q, limit } });
  return data;
}

export async function fetchMed(slug) {
  const { data } = await http.get(`/medications/${slug}`);
  return data;
}

export async function fetchAnalogs(slug, limit = 8) {
  const { data } = await http.get(`/medications/${slug}/analogs`, { params: { limit } });
  return data;
}

// Static helpers to keep current presentational components working
// without major refactors.
export function findPharmacyById(pharmacies, id) {
  return pharmacies.find((p) => p.id === id);
}

export function pharmaciesByCity(pharmacies, city) {
  return pharmacies.filter((p) => p.city === city);
}
