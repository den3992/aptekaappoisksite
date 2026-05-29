'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useCity } from '../../../context/CityContext';
import { fetchCategories } from '../../../api/client';
import CategoryIcon from '../../../components/CategoryIcon';
import { getCategoryStyle } from '../../../lib/categoryStyles';

export default function Categories() {
  const { city, cities, setCity } = useCity();
  const { city: cityParam } = useParams();
  const [cats, setCats] = useState([]);

  useEffect(() => {
    if (cityParam && cities) {
      const f = cities.find(c => c.id === cityParam);
      if (f && f.id !== city.id) setCity(f);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cityParam]);

  useEffect(() => {
    fetchCategories().then(setCats).catch(() => {});
  }, []);

  return (
    <div className="max-w-7xl mx-auto px-4 py-5 md:py-8">
      <nav className="text-xs text-slate-500 mb-4">
        <Link href={`/${city.id}`} className="hover:text-emerald-700">Главная</Link>
        <span className="mx-1.5">/</span><span>Категории</span>
      </nav>
      <h1 className="text-2xl sm:text-3xl md:text-4xl font-bold text-slate-900 mb-2 leading-tight">Категории препаратов</h1>
      <p className="text-slate-500 mb-6 md:mb-8 text-sm md:text-base">Выберите направление лечения</p>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 md:gap-3" data-testid="categories-grid">
        {cats.filter(c => c.slug !== 'other').map(c => {
          const icon = getCategoryStyle(c.slug);
          return (
            <Link key={c.slug} href={`/${city.id}/kategorii/${c.slug}`} className="cat-card bg-white border border-slate-100 rounded-xl p-4 md:p-5 flex flex-col active:bg-slate-50 transition">
              <div className="w-10 h-10 md:w-12 md:h-12 rounded-lg flex items-center justify-center mb-3 md:mb-4" style={{ background: icon.color, color: icon.accent }}>
                <CategoryIcon name={icon.icon} className="w-5 h-5 md:w-6 md:h-6" />
              </div>
              <div className="font-semibold text-slate-900 mb-1 text-sm md:text-base leading-tight">{c.title}</div>
              <div className="text-[11px] md:text-xs text-slate-500">{c.count.toLocaleString('ru')} препаратов</div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
