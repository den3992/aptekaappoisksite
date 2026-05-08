import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { CATEGORIES, MEDICATIONS } from '../mock';
import CategoryIcon from '../components/CategoryIcon';
import MedCard from '../components/MedCard';

export default function CategoryDetail() {
  const { slug } = useParams();
  const cat = CATEGORIES.find(c => c.slug === slug);
  const meds = MEDICATIONS.filter(m => m.category === slug);

  if (!cat) return (
    <div className="max-w-7xl mx-auto px-4 py-16 text-center">
      <h1 className="text-2xl font-bold mb-2">Категория не найдена</h1>
      <Link to="/kategorii" className="text-emerald-700 hover:underline">К выбору категории</Link>
    </div>
  );

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <nav className="text-xs text-slate-500 mb-4">
        <Link to="/" className="hover:text-emerald-700">Главная</Link>
        <span className="mx-1.5">/</span>
        <Link to="/kategorii" className="hover:text-emerald-700">Категории</Link>
        <span className="mx-1.5">/</span>
        <span>{cat.title}</span>
      </nav>

      <div className="flex items-center gap-4 mb-8">
        <div className="w-14 h-14 rounded-xl flex items-center justify-center" style={{ background: cat.color, color: cat.accent }}>
          <CategoryIcon name={cat.icon} className="w-7 h-7" />
        </div>
        <div>
          <h1 className="text-3xl md:text-4xl font-bold text-slate-900">{cat.title}</h1>
          <p className="text-slate-500 text-sm mt-1">{meds.length} препаратов в категории</p>
        </div>
      </div>

      {meds.length === 0 ? (
        <div className="bg-white border border-slate-100 rounded-xl p-12 text-center text-slate-500">В этой категории пока нет препаратов</div>
      ) : (
        <div className="grid sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {meds.map(m => <MedCard key={m.slug} med={m} />)}
        </div>
      )}
    </div>
  );
}
