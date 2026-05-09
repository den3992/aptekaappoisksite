import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { MapPin, Phone, Clock, ChevronRight, Star, Search } from 'lucide-react';
import { findPharmacyById, MEDICATIONS, PRICES } from '../mock';
import { loadYmaps } from '../lib/ymaps';

export default function PharmacyDetail() {
  const { id } = useParams();
  const ph = findPharmacyById(id);
  const [q, setQ] = useState('');
  const ref = useRef(null);
  const mapRef = useRef(null);

  useEffect(() => {
    if (!ph) return;
    let cancelled = false;
    loadYmaps().then(ymaps => {
      if (cancelled) return;
      if (mapRef.current) { mapRef.current.destroy(); mapRef.current = null; }
      const m = new ymaps.Map(ref.current, { center: [ph.lat, ph.lng], zoom: 15, controls: ['zoomControl'] }, { suppressMapOpenBlock: true });
      const placemark = new ymaps.Placemark([ph.lat, ph.lng], {
        balloonContent: `<strong>${ph.name}</strong><br/>${ph.address}`,
      }, { preset: 'islands#greenIcon' });
      m.geoObjects.add(placemark);
      mapRef.current = m;
    });
    return () => { cancelled = true; if (mapRef.current) { mapRef.current.destroy(); mapRef.current = null; } };
  }, [ph]);

  const items = useMemo(() => {
    if (!ph) return [];
    const list = [];
    Object.entries(PRICES).forEach(([slug, byCity]) => {
      const arr = byCity[ph.city] || [];
      const found = arr.find(x => x.pharmacyId === ph.id);
      if (found) {
        const med = MEDICATIONS.find(m => m.slug === slug);
        if (med) list.push({ med, ...found });
      }
    });
    return list.filter(x => q ? x.med.name.toLowerCase().includes(q.toLowerCase()) : true).sort((a,b) => a.med.name.localeCompare(b.med.name, 'ru'));
  }, [ph, q]);

  if (!ph) return (
    <div className="max-w-7xl mx-auto px-4 py-16 text-center">
      <h1 className="text-2xl font-bold mb-2">Аптека не найдена</h1>
      <Link to="/apteki" className="text-emerald-700 hover:underline">К списку аптек</Link>
    </div>
  );

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <nav className="text-xs text-slate-500 mb-4 flex items-center gap-1.5">
        <Link to="/" className="hover:text-emerald-700">Главная</Link>
        <ChevronRight className="w-3 h-3" />
        <Link to="/apteki" className="hover:text-emerald-700">Аптеки</Link>
        <ChevronRight className="w-3 h-3" />
        <span>{ph.name}</span>
      </nav>

      <div className="grid lg:grid-cols-[1fr_400px] gap-6 mb-10">
        <div>
          <h1 className="text-3xl md:text-4xl font-bold text-slate-900">{ph.name}</h1>
          <div className="flex items-center gap-3 mt-2 text-sm text-slate-500">
            <span>Сеть: <span className="text-slate-700 font-medium">{ph.chain}</span></span>
            <span className="inline-flex items-center gap-1 text-amber-700"><Star className="w-3.5 h-3.5 fill-amber-400 text-amber-400" /> {ph.rating}</span>
          </div>
          <div className="mt-5 grid sm:grid-cols-3 gap-3">
            <div className="bg-slate-50 rounded-lg p-3"><div className="flex items-center gap-1.5 text-[11px] text-slate-500 uppercase tracking-wide"><MapPin className="w-3 h-3" /> Адрес</div><div className="text-sm font-medium text-slate-800 mt-1">{ph.address}</div>{ph.metro && <div className="text-xs text-emerald-700 mt-0.5">м. {ph.metro}</div>}</div>
            <div className="bg-slate-50 rounded-lg p-3"><div className="flex items-center gap-1.5 text-[11px] text-slate-500 uppercase tracking-wide"><Phone className="w-3 h-3" /> Телефон</div><div className="text-sm font-medium text-slate-800 mt-1">{ph.phone}</div></div>
            <div className="bg-slate-50 rounded-lg p-3"><div className="flex items-center gap-1.5 text-[11px] text-slate-500 uppercase tracking-wide"><Clock className="w-3 h-3" /> Режим</div><div className="text-sm font-medium text-slate-800 mt-1">{ph.hours}</div></div>
          </div>
        </div>
        <div ref={ref} className="w-full h-72 lg:h-full rounded-xl overflow-hidden border border-slate-100" />
      </div>

      <section>
        <div className="flex items-end justify-between mb-4">
          <h2 className="text-2xl font-bold text-slate-900">Ассортимент аптеки</h2>
          <div className="text-sm text-slate-500">{items.length} позиций</div>
        </div>
        <div className="input-focus border border-slate-200 rounded-lg flex items-center bg-white max-w-md mb-4 transition">
          <Search className="w-4 h-4 text-slate-400 ml-3" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск препарата в аптеке…" className="flex-1 px-3 py-2.5 text-sm bg-transparent outline-none" />
        </div>
        <div className="bg-white border border-slate-100 rounded-xl divide-y divide-slate-100">
          {items.map(it => (
            <Link key={it.med.slug} to={`/preparaty/${it.med.slug}`} className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-emerald-50/40 transition">
              <div>
                <div className="font-medium text-slate-900">{it.med.name}</div>
                <div className="text-xs text-slate-500">{it.med.form} · {it.med.manufacturer}</div>
              </div>
              <div className="text-right">
                <div className="font-bold text-emerald-700">{it.price} ₽</div>
                <div className="text-[11px] text-slate-500">{it.qty} шт</div>
              </div>
            </Link>
          ))}
          {items.length === 0 && <div className="p-12 text-center text-slate-500">Ничего не найдено</div>}
        </div>
      </section>
    </div>
  );
}
