import React, { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { MapPin, Phone, Clock, Search, Star } from 'lucide-react';
import { useCity } from '../context/CityContext';
import { fetchPharmacies } from '../api/client';
import SEOHead from '../components/SEOHead';

export default function PharmaciesList() {
  const { city, cities, setCity } = useCity();
  const { city: cityParam } = useParams();
  const [q, setQ] = useState('');
  const [list, setList] = useState([]);

  useEffect(() => {
    if (cityParam && cities) {
      const f = cities.find(c => c.id === cityParam);
      if (f && f.id !== city.id) setCity(f);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cityParam]);

  useEffect(() => {
    fetchPharmacies(city.id).then(setList).catch(() => setList([]));
  }, [city.id]);

  const filtered = useMemo(() => list.filter(p => q ? `${p.name} ${p.address} ${p.chain}`.toLowerCase().includes(q.toLowerCase()) : true), [list, q]);

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <SEOHead seo={{
        title: `Аптеки в ${city.inLoc} — адреса, телефоны, режим работы | АптекаА`,
        description: `Список аптек-партнёров в ${city.inLoc} с адресами, телефонами и режимом работы.`,
      }} />
      <nav className="text-xs text-slate-500 mb-4">
        <Link to={`/${city.id}`} className="hover:text-emerald-700">Главная</Link>
        <span className="mx-1.5">/</span><span>Аптеки</span>
      </nav>
      <h1 className="text-3xl md:text-4xl font-bold text-slate-900 mb-2">Аптеки в {city.inLoc}</h1>
      <p className="text-slate-500 mb-6">{filtered.length} аптек-партнёров</p>

      <div className="input-focus border border-slate-200 rounded-lg flex items-center bg-white max-w-md mb-6 transition">
        <Search className="w-4 h-4 text-slate-400 ml-3" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск по названию или адресу…" className="flex-1 px-3 py-2.5 text-sm bg-transparent outline-none" />
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3" data-testid="pharmacies-list">
        {filtered.map(ph => (
          <Link key={ph.id} to={`/${city.id}/apteki/${ph.id}`} className="bg-white border border-slate-100 rounded-xl p-5 hover:border-emerald-200 hover:shadow-card transition">
            <div className="flex items-start justify-between gap-2">
              <h3 className="font-semibold text-slate-900">{ph.name}</h3>
              {ph.rating && (
                <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-700 bg-amber-50 px-2 py-0.5 rounded"><Star className="w-3 h-3 fill-amber-400 text-amber-400" /> {ph.rating}</span>
              )}
            </div>
            <p className="text-xs text-slate-400 mt-0.5">Сеть: {ph.chain}</p>
            <div className="mt-3 space-y-1.5 text-sm text-slate-600">
              <div className="flex items-start gap-2"><MapPin className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" /> {ph.address}</div>
              {ph.metro && <div className="text-xs text-emerald-700 ml-6">м. {ph.metro}</div>}
              <div className="flex items-center gap-2"><Phone className="w-4 h-4 text-emerald-600" /> {ph.phone}</div>
              <div className="flex items-center gap-2"><Clock className="w-4 h-4 text-emerald-600" /> {ph.hours}</div>
            </div>
          </Link>
        ))}
      </div>
      {filtered.length === 0 && (
        <div className="bg-white border border-slate-100 rounded-xl p-12 text-center text-slate-500">Аптеки не найдены</div>
      )}
    </div>
  );
}
