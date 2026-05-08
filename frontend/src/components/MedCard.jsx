import React from 'react';
import { Link } from 'react-router-dom';
import { useCity } from '../context/CityContext';
import { PRICES } from '../mock';
import { Pill } from 'lucide-react';

export default function MedCard({ med }) {
  const { city } = useCity();
  const prices = (PRICES[med.slug]?.[city.id] || []).map(p => p.price).sort((a,b) => a-b);
  const min = prices[0];
  const offers = prices.length;

  return (
    <Link to={`/preparaty/${med.slug}`} className="med-card group bg-white border border-slate-100 rounded-xl p-3 flex flex-col h-full">
      <div className="aspect-square w-full rounded-lg bg-slate-50 overflow-hidden mb-3 flex items-center justify-center">
        {med.image ? (
          <img src={med.image} alt={med.name} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" loading="lazy" />
        ) : (
          <Pill className="w-10 h-10 text-emerald-300" />
        )}
      </div>
      <div className="flex-1">
        {med.rx && (
          <span className="inline-block text-[10px] font-semibold uppercase tracking-wide bg-rose-50 text-rose-700 px-2 py-0.5 rounded mb-1.5">По рецепту</span>
        )}
        <h3 className="text-sm font-semibold text-slate-900 line-clamp-2 leading-snug">{med.name}</h3>
        <p className="text-xs text-slate-500 mt-1 line-clamp-1">{med.form}, {med.pack}</p>
        <p className="text-xs text-slate-400 mt-0.5">{med.manufacturer}</p>
      </div>
      <div className="mt-3 pt-3 border-t border-slate-100 flex items-end justify-between">
        <div>
          <div className="text-[11px] text-slate-500">от</div>
          <div className="text-lg font-bold text-emerald-700">{min} ₽</div>
        </div>
        <div className="text-[11px] text-slate-500 text-right">в {offers} аптеках</div>
      </div>
    </Link>
  );
}
