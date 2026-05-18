import { formatName, formatManufacturer } from "../utils/text";
import React, { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ChevronLeft, ChevronRight, Search } from 'lucide-react';
import { useCity } from '../context/CityContext';
import { searchMeds } from '../api/client';
import SEOHead from '../components/SEOHead';

const LETTERS = ['А','Б','В','Г','Д','Е','Ж','З','И','К','Л','М','Н','О','П','Р','С','Т','У','Ф','Х','Ц','Ч','Ш','Щ','Э','Ю','Я'];
const PAGE_SIZE = 48;

export default function Catalog() {
  const { city, cities, setCity } = useCity();
  const { city: cityParam } = useParams();
  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [letter, setLetter] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);

  // Sync URL city → context
  useEffect(() => {
    if (cityParam && cities) {
      const f = cities.find(c => c.id === cityParam);
      if (f && f.id !== city.id) setCity(f);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cityParam]);

  // Debounce search input
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  // Reset to first page when filters change
  useEffect(() => { setPage(1); }, [letter, debouncedQ]);

  // Fetch data
  useEffect(() => {
    setLoading(true);
    let cancelled = false;
    searchMeds({
      q: debouncedQ || undefined,
      prefix: letter || undefined,
      page,
      pageSize: PAGE_SIZE,
    }).then(res => {
      if (!cancelled) setData(res);
    }).catch(() => { if (!cancelled) setData({ items: [], total: 0 }); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [debouncedQ, letter, page]);

  const totalPages = useMemo(() => Math.max(1, Math.ceil((data.total || 0) / PAGE_SIZE)), [data.total]);

  return (
    <div className="max-w-7xl mx-auto px-4 py-5 md:py-8">
      <SEOHead seo={{
        title: `Каталог лекарств А–Я в аптеках ${city.inGen} | АптекаА`,
        description: `Полный алфавитный каталог лекарственных препаратов в аптеках ${city.inGen}.`,
      }} />
      <nav className="text-xs text-slate-500 mb-4">
        <Link to={`/${city.id}`} className="hover:text-emerald-700">Главная</Link>
        <span className="mx-1.5">/</span><span>Каталог препаратов</span>
      </nav>
      <h1 className="text-2xl sm:text-3xl md:text-4xl font-bold text-slate-900 mb-2 leading-tight">Каталог лекарств А–Я</h1>
      <p className="text-slate-500 mb-6">{(data.total || 0).toLocaleString('ru')} препаратов в реестре</p>

      <div className="input-focus border border-slate-200 rounded-lg flex items-center bg-white max-w-md mb-6 transition">
        <Search className="w-4 h-4 text-slate-400 ml-3" />
        <input type="search" inputMode="search" lang="ru" autoComplete="off" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Найти в каталоге…" aria-label="Поиск в каталоге" className="flex-1 px-3 py-3 md:py-2.5 text-[15px] md:text-sm bg-transparent outline-none" data-testid="catalog-search-input" />
      </div>

      <div className="flex flex-wrap gap-1 md:gap-1.5 mb-6 md:mb-8 bg-white border border-slate-100 rounded-xl p-2 md:p-3" data-testid="letter-filter">
        <button onClick={() => setLetter('')} className={`px-2.5 md:px-3 h-9 md:h-auto md:py-1.5 text-sm rounded-md font-medium ${!letter ? 'bg-emerald-600 text-white' : 'active:bg-emerald-50'}`}>Все</button>
        {LETTERS.map(l => {
          const active = letter === l;
          return (
            <button key={l} onClick={() => setLetter(l)} className={`w-8 h-8 md:w-9 md:h-9 text-sm rounded-md font-medium ${active ? 'bg-emerald-600 text-white' : 'active:bg-emerald-50 text-slate-700'}`}>{l}</button>
          );
        })}
      </div>

      {loading ? (
        <div className="text-center text-slate-500 py-16">Загрузка…</div>
      ) : data.items.length === 0 ? (
        <div className="text-center text-slate-500 py-16">Ничего не найдено</div>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2" data-testid="catalog-list">
            {data.items.map(m => (
              <Link key={m.slug} to={`/${city.id}/preparaty/${m.slug}`} className="block bg-white border border-slate-100 rounded-xl p-4 hover:border-emerald-300 transition">
                {m.rx && (
                  <span className="inline-block text-[10px] font-semibold uppercase tracking-wide bg-rose-50 text-rose-700 px-2 py-0.5 rounded mb-1.5">
                    Отпускается по рецепту
                  </span>
                )}
                <div className="text-sm font-semibold text-slate-900 leading-tight">{formatName(m.name)}</div>
                <div className="text-xs text-slate-500 mt-0.5 line-clamp-2">{[m.form?.toLowerCase(), m.dosage].filter(Boolean).join(', ')}</div>
                <div className="text-xs text-slate-400 mt-1.5 truncate">{formatManufacturer(m.manufacturer)}</div>
              </Link>
            ))}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 mt-8" data-testid="catalog-pager">
              <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}
                className="px-3 h-11 rounded-lg border border-slate-200 disabled:opacity-40 hover:border-emerald-400 flex items-center gap-1 text-sm">
                <ChevronLeft className="w-4 h-4" /> Назад
              </button>
              <span className="text-sm text-slate-600">Страница <strong>{page}</strong> из <strong>{totalPages.toLocaleString('ru')}</strong></span>
              <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages}
                className="px-3 h-11 rounded-lg border border-slate-200 disabled:opacity-40 hover:border-emerald-400 flex items-center gap-1 text-sm">
                Вперёд <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
