import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useCity } from '../context/CityContext';
import { fetchCategories } from '../api/client';
import CategoryIcon from '../components/CategoryIcon';
import SEOHead from '../components/SEOHead';
import { CATEGORIES as STATIC_CATS } from '../mock';

const ICON_BY_SLUG = STATIC_CATS.reduce((m, c) => { m[c.slug] = c; return m; }, {});

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
    <div className="max-w-7xl mx-auto px-4 py-8">
      <SEOHead seo={{
        title: `Категории препаратов в аптеках ${city.inGen} | АптекаА`,
        description: `Все категории лекарственных препаратов, доступные в аптеках ${city.inGen}.`,
      }} />
      <nav className="text-xs text-slate-500 mb-4">
        <Link to={`/${city.id}`} className="hover:text-emerald-700">Главная</Link>
        <span className="mx-1.5">/</span><span>Категории</span>
      </nav>
      <h1 className="text-3xl md:text-4xl font-bold text-slate-900 mb-2">Категории препаратов</h1>
      <p className="text-slate-500 mb-8">Выберите направление лечения</p>

      <div className="grid sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3" data-testid="categories-grid">
        {cats.filter(c => c.slug !== 'other').map(c => {
          const icon = ICON_BY_SLUG[c.slug] || { icon: 'Pill', color: '#F1F5F9', accent: '#475569' };
          return (
            <Link key={c.slug} to={`/${city.id}/kategorii/${c.slug}`} className="cat-card bg-white border border-slate-100 rounded-xl p-5 flex flex-col">
              <div className="w-12 h-12 rounded-lg flex items-center justify-center mb-4" style={{ background: icon.color, color: icon.accent }}>
                <CategoryIcon name={icon.icon} className="w-6 h-6" />
              </div>
              <div className="font-semibold text-slate-900 mb-1">{c.title}</div>
              <div className="text-xs text-slate-500">{c.count.toLocaleString('ru')} препаратов</div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
