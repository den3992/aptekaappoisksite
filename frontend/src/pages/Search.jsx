import React, { useMemo, useState } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { Search as SearchIcon, SlidersHorizontal, Filter } from 'lucide-react';
import { MEDICATIONS, CATEGORIES, PRICES } from '../mock';
import { useCity } from '../context/CityContext';
import MedCard from '../components/MedCard';

export default function Search() {
  const [params, setParams] = useSearchParams();
  const q = params.get('q') || '';
  const cat = params.get('kategoriya') || '';
  const [sort, setSort] = useState('relevance');
  const [onlyOTC, setOnlyOTC] = useState(false);
  const { city } = useCity();

  const results = useMemo(() => {
    const term = q.toLowerCase();
    let arr = MEDICATIONS.filter(m => {
      if (cat && m.category !== cat) return false;
      if (onlyOTC && m.rx) return false;
      if (!term) return true;
      return [m.name, m.mnn, m.manufacturer, m.form].some(x => x.toLowerCase().includes(term));
    });
    const minPrice = (slug) => Math.min(...((PRICES[slug]?.[city.id] || []).map(p => p.price)));
    if (sort === 'price-asc') arr = [...arr].sort((a,b) => minPrice(a.slug) - minPrice(b.slug));
    if (sort === 'price-desc') arr = [...arr].sort((a,b) => minPrice(b.slug) - minPrice(a.slug));
    if (sort === 'name') arr = [...arr].sort((a,b) => a.name.localeCompare(b.name, 'ru'));
    return arr;
  }, [q, cat, onlyOTC, sort, city.id]);

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <nav className="text-xs text-slate-500 mb-4">
        <Link to="/" className="hover:text-emerald-700">Главная</Link>
        <span className="mx-1.5">/</span><span>Поиск</span>
      </nav>

      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-slate-900">
            {q ? <>По запросу «<span className="text-emerald-700">{q}</span>»</> : 'Результаты поиска'}
          </h1>
          <p className="text-slate-500 mt-1 text-sm">Найдено: {results.length} · Город: {city.name}</p>
        </div>
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="w-4 h-4 text-slate-500" />
          <select value={sort} onChange={(e) => setSort(e.target.value)} className="text-sm border border-slate-200 rounded-md px-3 py-2 bg-white outline-none focus:border-emerald-400">
            <option value="relevance">По релевантности</option>
            <option value="price-asc">Сначала дешевле</option>
            <option value="price-desc">Сначала дороже</option>
            <option value="name">По названию</option>
          </select>
        </div>
      </div>

      <div className="grid lg:grid-cols-[260px_1fr] gap-6">
        <aside className="bg-white border border-slate-100 rounded-xl p-4 h-fit lg:sticky lg:top-32">
          <div className="flex items-center gap-2 mb-3">
            <Filter className="w-4 h-4 text-slate-500" />
            <h3 className="font-semibold text-slate-900 text-sm">Фильтры</h3>
          </div>
          <div className="text-sm">
            <label className="flex items-center gap-2 mb-3 cursor-pointer">
              <input type="checkbox" checked={onlyOTC} onChange={(e) => setOnlyOTC(e.target.checked)} className="w-4 h-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500" />
              Без рецепта
            </label>
            <div className="mt-4">
              <div className="text-xs uppercase tracking-wide text-slate-400 mb-2 font-medium">Категория</div>
              <div className="space-y-1">
                <button onClick={() => { params.delete('kategoriya'); setParams(params); }} className={`block w-full text-left px-2 py-1.5 rounded ${!cat ? 'bg-emerald-50 text-emerald-800 font-medium' : 'hover:bg-slate-50'}`}>Все</button>
                {CATEGORIES.map(c => (
                  <button key={c.slug} onClick={() => { params.set('kategoriya', c.slug); setParams(params); }} className={`block w-full text-left px-2 py-1.5 rounded ${cat === c.slug ? 'bg-emerald-50 text-emerald-800 font-medium' : 'hover:bg-slate-50'}`}>{c.title}</button>
                ))}
              </div>
            </div>
          </div>
        </aside>

        <div>
          {results.length === 0 ? (
            <div className="bg-white border border-slate-100 rounded-xl p-12 text-center">
              <div className="w-16 h-16 mx-auto bg-slate-50 rounded-full flex items-center justify-center mb-4">
                <SearchIcon className="w-7 h-7 text-slate-400" />
              </div>
              <h3 className="text-lg font-semibold text-slate-900 mb-1">Ничего не найдено</h3>
              <p className="text-slate-500 text-sm">Попробуйте изменить запрос или проверьте орфографию</p>
            </div>
          ) : (
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
              {results.map(m => <MedCard key={m.slug} med={m} />)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
