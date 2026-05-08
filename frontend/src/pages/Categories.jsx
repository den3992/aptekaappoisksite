import React from 'react';
import { Link } from 'react-router-dom';
import { CATEGORIES, MEDICATIONS } from '../mock';
import CategoryIcon from '../components/CategoryIcon';

export default function Categories() {
  const counts = CATEGORIES.reduce((acc, c) => {
    acc[c.slug] = MEDICATIONS.filter(m => m.category === c.slug).length;
    return acc;
  }, {});

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <nav className="text-xs text-slate-500 mb-4">
        <Link to="/" className="hover:text-emerald-700">Главная</Link>
        <span className="mx-1.5">/</span><span>Категории</span>
      </nav>
      <h1 className="text-3xl md:text-4xl font-bold text-slate-900 mb-2">Категории препаратов</h1>
      <p className="text-slate-500 mb-8">Выберите направление лечения</p>

      <div className="grid sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        {CATEGORIES.map(c => (
          <Link key={c.slug} to={`/kategorii/${c.slug}`} className="cat-card bg-white border border-slate-100 rounded-xl p-5 flex flex-col">
            <div className="w-12 h-12 rounded-lg flex items-center justify-center mb-4" style={{ background: c.color, color: c.accent }}>
              <CategoryIcon name={c.icon} className="w-6 h-6" />
            </div>
            <div className="font-semibold text-slate-900 mb-1">{c.title}</div>
            <div className="text-xs text-slate-500">{counts[c.slug]} препаратов</div>
          </Link>
        ))}
      </div>
    </div>
  );
}
