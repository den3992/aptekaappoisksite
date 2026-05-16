import { formatName, formatManufacturer, dedupeMeds } from "../utils/text";
import React, { useEffect, useState } from 'react';
import { useSearchParams, useParams, Link } from 'react-router-dom';
import { Search as SearchIcon, SlidersHorizontal, Filter, ChevronLeft, ChevronRight, X } from 'lucide-react';
import { useCity } from '../context/CityContext';
import { searchMeds, fetchCategories } from '../api/client';
import SEOHead from '../components/SEOHead';
import { searchSEO } from '../seo';
import {
  Drawer, DrawerContent, DrawerHeader, DrawerTitle, DrawerDescription, DrawerClose,
} from '../components/ui/drawer';

const PAGE_SIZE = 24;

export default function Search() {
  const [params, setParams] = useSearchParams();
  const { city: cityParam } = useParams();
  const q = params.get('q') || '';
  const cat = params.get('kategoriya') || '';
  const page = Math.max(1, Number(params.get('page')) || 1);
  const [onlyOTC, setOnlyOTC] = useState(false);
  const { city, cities, setCity } = useCity();
  const [data, setData] = useState({ items: [], total: 0, page: 1 });
  const [loading, setLoading] = useState(false);
  const [categories, setCategories] = useState([]);
  const [filtersOpen, setFiltersOpen] = useState(false);

  // Sync URL city → context
  useEffect(() => {
    if (cityParam && cities) {
      const found = cities.find(c => c.id === cityParam);
      if (found && found.id !== city.id) setCity(found);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cityParam]);

  useEffect(() => {
    fetchCategories().then(setCategories).catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    searchMeds({ q, category: cat, rx: onlyOTC ? false : undefined, page, pageSize: PAGE_SIZE })
      .then((res) => { if (!cancelled) setData(res); })
      .catch(() => { if (!cancelled) setData({ items: [], total: 0, page: 1 }); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [q, cat, onlyOTC, page]);

  const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  const cityId = city.id;
  const seo = searchSEO(cityId, q);
  const activeCat = categories.find(c => c.slug === cat);
  const activeCount = (cat ? 1 : 0) + (onlyOTC ? 1 : 0);

  const setPage = (p) => {
    const np = new URLSearchParams(params);
    if (p > 1) np.set('page', String(p)); else np.delete('page');
    setParams(np);
  };

  const clearCategory = () => {
    const np = new URLSearchParams(params);
    np.delete('kategoriya'); np.delete('page'); setParams(np);
  };
  const clearAll = () => {
    const np = new URLSearchParams(params);
    np.delete('kategoriya'); np.delete('page'); setParams(np);
    setOnlyOTC(false);
  };

  // Reusable filters body (used in both desktop sidebar and mobile drawer)
  const FiltersBody = ({ onPick }) => (
    <div className="text-sm">
      <label className="flex items-center gap-2 mb-3 cursor-pointer min-h-[44px]">
        <input
          type="checkbox"
          checked={onlyOTC}
          onChange={(e) => setOnlyOTC(e.target.checked)}
          className="w-4 h-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
          data-testid="filter-otc"
        />
        Без рецепта
      </label>
      <div className="mt-4">
        <div className="text-xs uppercase tracking-wide text-slate-400 mb-2 font-medium">Категория</div>
        <div className="space-y-1 lg:max-h-[calc(100vh-10rem)] lg:overflow-y-auto no-scrollbar">
          <button
            onClick={() => { clearCategory(); onPick && onPick(); }}
            className={`block w-full text-left px-2 py-2 rounded ${!cat ? 'bg-emerald-50 text-emerald-800 font-medium' : 'hover:bg-slate-50'}`}
          >Все</button>
          {categories.map(c => (
            <button
              key={c.slug}
              onClick={() => { const np = new URLSearchParams(params); np.set('kategoriya', c.slug); np.delete('page'); setParams(np); onPick && onPick(); }}
              className={`flex items-center justify-between w-full text-left px-2 py-2 rounded ${cat === c.slug ? 'bg-emerald-50 text-emerald-800 font-medium' : 'hover:bg-slate-50'}`}
            >
              <span>{c.title}</span>
              <span className="text-xs text-slate-400">{c.count}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 md:py-8">
      <SEOHead seo={seo} />

      <nav className="text-xs text-slate-500 mb-4">
        <Link to={`/${cityId}`} className="hover:text-emerald-700">Главная</Link>
        <span className="mx-1.5">/</span><span>Поиск</span>
      </nav>

      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4 mb-4 md:mb-6">
        <div>
          <h1 className="text-xl sm:text-2xl md:text-3xl font-bold text-slate-900">
            {q ? <>По запросу «<span className="text-emerald-700">{q}</span>»</> : 'Каталог препаратов'}
          </h1>
          <p className="text-slate-500 mt-1 text-sm">
            {loading ? 'Идёт поиск…' : <>Найдено: <strong>{data.total.toLocaleString('ru')}</strong> · Город: {city.name}</>}
          </p>
        </div>
      </div>

      {/* Mobile filter trigger + active chips */}
      <div className="lg:hidden mb-4 flex items-center gap-2 flex-wrap" data-testid="mobile-filter-bar">
        <button
          type="button"
          onClick={() => setFiltersOpen(true)}
          className="inline-flex items-center gap-2 px-3 h-10 rounded-xl border border-slate-200 bg-white text-sm font-medium text-slate-800 active:bg-slate-50"
          data-testid="mobile-filter-btn"
        >
          <SlidersHorizontal className="w-4 h-4" />
          Фильтры
          {activeCount > 0 && (
            <span className="ml-1 inline-flex items-center justify-center min-w-[20px] h-5 px-1 rounded-full bg-emerald-600 text-white text-[11px] font-semibold">
              {activeCount}
            </span>
          )}
        </button>
        {activeCat && (
          <button
            type="button"
            onClick={clearCategory}
            className="inline-flex items-center gap-1.5 pl-3 pr-2 h-10 rounded-xl bg-emerald-50 text-emerald-800 border border-emerald-200 text-sm font-medium"
            data-testid="mobile-chip-cat"
          >
            {activeCat.title}
            <X className="w-3.5 h-3.5" />
          </button>
        )}
        {onlyOTC && (
          <button
            type="button"
            onClick={() => setOnlyOTC(false)}
            className="inline-flex items-center gap-1.5 pl-3 pr-2 h-10 rounded-xl bg-emerald-50 text-emerald-800 border border-emerald-200 text-sm font-medium"
            data-testid="mobile-chip-otc"
          >
            Без рецепта
            <X className="w-3.5 h-3.5" />
          </button>
        )}
        {activeCount > 1 && (
          <button
            type="button"
            onClick={clearAll}
            className="ml-auto text-xs text-slate-500 underline-offset-2 hover:underline"
            data-testid="mobile-clear-all"
          >
            Сбросить
          </button>
        )}
      </div>

      <div className="grid lg:grid-cols-[260px_1fr] gap-6">
        <aside className="hidden lg:block bg-white border border-slate-100 rounded-xl p-4 h-fit lg:sticky lg:top-32" data-testid="search-filters">
          <div className="flex items-center gap-2 mb-3">
            <Filter className="w-4 h-4 text-slate-500" />
            <h3 className="font-semibold text-slate-900 text-sm">Фильтры</h3>
          </div>
          <FiltersBody />
        </aside>

        <div data-testid="search-results">
          {!loading && data.items.length === 0 ? (
            <div className="bg-white border border-slate-100 rounded-xl p-8 md:p-12 text-center">
              <div className="w-14 h-14 md:w-16 md:h-16 mx-auto bg-slate-50 rounded-full flex items-center justify-center mb-4">
                <SearchIcon className="w-6 h-6 md:w-7 md:h-7 text-slate-400" />
              </div>
              <h3 className="text-base md:text-lg font-semibold text-slate-900 mb-1">Ничего не найдено</h3>
              <p className="text-slate-500 text-sm">Попробуйте изменить запрос или проверьте орфографию</p>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {dedupeMeds(data.items).map(m => (
                  <MedListCard key={m.slug} med={m} cityId={cityId} />
                ))}
              </div>

              {totalPages > 1 && (
                <div className="flex items-center justify-center gap-2 mt-6 md:mt-8" data-testid="search-pagination">
                  <button
                    onClick={() => setPage(page - 1)}
                    disabled={page <= 1}
                    className="px-3 h-11 rounded-lg border border-slate-200 disabled:opacity-40 hover:border-emerald-400 flex items-center gap-1 text-sm"
                  >
                    <ChevronLeft className="w-4 h-4" /> Назад
                  </button>
                  <span className="text-sm text-slate-600">
                    Страница <strong>{page}</strong> из <strong>{totalPages}</strong>
                  </span>
                  <button
                    onClick={() => setPage(page + 1)}
                    disabled={page >= totalPages}
                    className="px-3 h-11 rounded-lg border border-slate-200 disabled:opacity-40 hover:border-emerald-400 flex items-center gap-1 text-sm"
                  >
                    Вперёд <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Mobile filters drawer */}
      <Drawer open={filtersOpen} onOpenChange={setFiltersOpen}>
        <DrawerContent className="lg:hidden" data-testid="mobile-filters-drawer">
          <DrawerHeader className="text-left flex-row items-center justify-between gap-3">
            <div className="flex-1">
              <DrawerTitle className="flex items-center gap-2">
                <Filter className="w-4 h-4 text-emerald-600" /> Фильтры
              </DrawerTitle>
              <DrawerDescription className="sr-only">Выберите категорию и тип отпуска</DrawerDescription>
            </div>
            {activeCount > 0 && (
              <button
                type="button"
                onClick={() => { clearAll(); }}
                className="text-xs text-slate-500 underline-offset-2 hover:underline"
              >Сбросить всё</button>
            )}
          </DrawerHeader>
          <div className="px-4 pb-2 max-h-[70vh] overflow-y-auto">
            <FiltersBody onPick={() => {}} />
          </div>
          <div className="px-4 pb-6 pt-2">
            <DrawerClose asChild>
              <button
                type="button"
                className="w-full h-12 rounded-xl bg-emerald-600 text-white font-semibold active:bg-emerald-700"
                data-testid="mobile-filters-apply"
              >
                Показать {data.total.toLocaleString('ru')} результатов
              </button>
            </DrawerClose>
          </div>
        </DrawerContent>
      </Drawer>
    </div>
  );
}

function MedListCard({ med, cityId }) {
  const formLower = (med.form || '').toLowerCase();
  return (
    <Link
      to={`/${cityId}/preparaty/${med.slug}`}
      data-testid="med-card"
      className="med-card block bg-white border border-slate-100 rounded-xl p-4 hover:border-emerald-300 active:bg-slate-50 transition"
    >
      {med.rx && (
        <span className="inline-block text-[10px] font-semibold uppercase tracking-wide bg-rose-50 text-rose-700 px-2 py-0.5 rounded mb-1.5">
          Отпускается по рецепту
        </span>
      )}
      <h3 className="font-semibold text-slate-900 text-base leading-tight">{formatName(med.name)}</h3>
      <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">
        {[formLower, med.dosage].filter(Boolean).join(', ')}
      </p>
      <p className="text-xs text-slate-400 mt-2">{[med.manufacturer, ...(med.also_manufacturers || [])].map(formatManufacturer).join(" / ")}</p>
      {med.mnn && (
        <p className="text-[11px] text-slate-400 mt-1">МНН: {med.mnn.toLowerCase()}</p>
      )}
    </Link>
  );
}
