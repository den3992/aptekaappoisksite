// Centralized API client with helpers backed by FastAPI catalog endpoints.
// Replaces the static `mock.js` data source.
import axios from 'axios';

// Изоморфный base URL:
// — на сервере (Server Components, Node-рантайм Next.js) идём напрямую
//   в backend по docker-сети, без обхода через edge nginx;
// — на клиенте (браузер пользователя) используем относительный `/api`,
//   который edge nginx уже умеет проксировать в backend.
export const API =
  typeof window === 'undefined'
    ? `${process.env.BACKEND_INTERNAL_URL || 'http://backend:8001'}/api`
    : '/api';

const http = axios.create({
  baseURL: API,
  timeout: 20000,
});

// In-memory caches for static lookups (cities, categories) so we don't hit
// the backend on every page navigation.
let _categoriesCache = null;

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

export async function fetchPharmacy(id, city) {
  const { data } = await http.get(`/pharmacies/${id}`, city ? { params: { city } } : undefined);
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

export async function fetchMed(slug, city) {
  const { data } = await http.get(`/medications/${slug}`, city ? { params: { city } } : undefined);
  return data;
}

export async function fetchAnalogs(slug, limit = 8) {
  const { data } = await http.get(`/medications/${slug}/analogs`, { params: { limit } });
  return data;
}

let _gorzdravStoresCache = {};
export async function fetchGorzdravStores(city = 'msk') {
  if (_gorzdravStoresCache[city]) return _gorzdravStoresCache[city];
  const { data } = await http.get('/gorzdrav/stores', { params: { city } });
  _gorzdravStoresCache[city] = data;
  return data;
}

// Per-store full info — lazy-loaded on marker click; cached forever in-memory.
let _gorzdravStoreDetailCache = {};
export async function fetchGorzdravStoreDetail(storeId) {
  if (_gorzdravStoreDetailCache[storeId]) return _gorzdravStoreDetailCache[storeId];
  const { data } = await http.get('/gorzdrav/stores/' + storeId);
  _gorzdravStoreDetailCache[storeId] = data;
  return data;
}

// Bulk fetch — для динамического списка "видно на карте".
// Возвращает только тех, кого ещё нет в кеше; уже закэшированных не запрашивает.
export async function fetchGorzdravStoresBulk(ids) {
  if (!ids || ids.length === 0) return [];
  const missing = ids.filter(id => !_gorzdravStoreDetailCache[id]);
  if (missing.length > 0) {
    const { data } = await http.get('/gorzdrav/stores/bulk', { params: { ids: missing.join(',') } });
    data.forEach(d => { _gorzdravStoreDetailCache[d.store_id] = d; });
  }
  return ids.map(id => _gorzdravStoreDetailCache[id]).filter(Boolean);
}
