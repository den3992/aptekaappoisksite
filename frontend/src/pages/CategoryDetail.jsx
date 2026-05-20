import { formatName, formatManufacturer } from "../utils/text";
import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useCity } from '../context/CityContext';
import { fetchCategories, searchMeds } from '../api/client';
import CategoryIcon from '../components/CategoryIcon';
import SEOHead from '../components/SEOHead';
import { categorySEO } from '../seo';
import { getCategoryStyle } from '../lib/categoryStyles';
const PAGE_SIZE = 24;

export default function CategoryDetail() {
  const { slug, city: cityParam } = useParams();
  const { city, cities, setCity } = useCity();
  const [cat, setCat] = useState(null);
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (cityParam && cities) {
      const f = cities.find(c => c.id === cityParam);
      if (f && f.id !== city.id) setCity(f);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cityParam]);

  useEffect(() => {
    fetchCategories().then((all) => setCat(all.find(c => c.slug === slug))).catch(() => {});
  }, [slug]);

  useEffect(() => {
    setLoading(true);
    let cancelled = false;
    searchMeds({ category: slug, page, pageSize: PAGE_SIZE })
      .then((res) => { if (!cancelled) setData(res); })
      .catch(() => { if (!cancelled) setData({ items: [], total: 0 }); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [slug, page]);

  const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));

  if (!cat) return (
    <div className="max-w-7xl mx-auto px-4 py-16 text-center text-slate-500">Загрузка категории…</div>
  );

  const icon = getCategoryStyle(slug);
  const seo = categorySEO(city.id, cat, data.total);

  return (
    <div className="max-w-7xl mx-auto px-4 py-5 md:py-8">
      <SEOHead seo={seo} />
      <nav className="text-xs text-slate-500 mb-4">
        <Link to={`/${city.id}`} className="hover:text-emerald-700">Главная</Link>
        <span className="mx-1.5">/</span>
        <Link to={`/${city.id}/kategorii`} className="hover:text-emerald-700">Категории</Link>
        <span className="mx-1.5">/</span><span>{cat.title}</span>
      </nav>

      <div className="flex items-center gap-3 md:gap-4 mb-6 md:mb-8">
        <div className="w-11 h-11 md:w-14 md:h-14 rounded-xl flex items-center justify-center shrink-0" style={{ background: icon.color, color: icon.accent }}>
          <CategoryIcon name={icon.icon} className="w-5 h-5 md:w-7 md:h-7" />
        </div>
        <div>
          <h1 className="text-xl sm:text-2xl md:text-3xl lg:text-4xl font-bold text-slate-900 leading-tight">{cat.title}</h1>
          <p className="text-slate-500 text-xs md:text-sm mt-0.5 md:mt-1">{data.total.toLocaleString('ru')} препаратов в категории</p>
        </div>
      </div>

      {!loading && data.items.length === 0 ? (
        <div className="bg-white border border-slate-100 rounded-xl p-12 text-center text-slate-500">В этой категории пока нет препаратов</div>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 md:gap-3">
            {data.items.map(m => (
              <Link key={m.slug} to={`/${city.id}/preparaty/${m.slug}`} className="med-card block bg-white border border-slate-100 rounded-xl p-4 hover:border-emerald-300 active:bg-slate-50 transition">
                {m.rx && (
                  <span className="inline-block text-[10px] font-semibold uppercase tracking-wide bg-rose-50 text-rose-700 px-2 py-0.5 rounded mb-1.5">
                    Отпускается по рецепту
                  </span>
                )}
                <h3 className="font-semibold text-slate-900 text-base leading-tight">{formatName(m.name)}</h3>
                <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">
                  {[m.form?.toLowerCase(), m.dosage].filter(Boolean).join(', ')}
                </p>
                <p className="text-xs text-slate-400 mt-2">{formatManufacturer(m.manufacturer)}</p>
              </Link>
            ))}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 mt-8">
              <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}
                className="px-3 h-11 rounded-lg border border-slate-200 disabled:opacity-40 hover:border-emerald-400 flex items-center gap-1 text-sm">
                <ChevronLeft className="w-4 h-4" /> Назад
              </button>
              <span className="text-sm text-slate-600">Страница <strong>{page}</strong> из <strong>{totalPages}</strong></span>
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
