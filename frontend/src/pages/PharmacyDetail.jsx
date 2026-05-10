import React, { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { MapPin, Phone, Clock, ChevronRight, Star, Navigation } from 'lucide-react';
import { useCity } from '../context/CityContext';
import { fetchPharmacy } from '../api/client';
import SEOHead from '../components/SEOHead';
import { pharmacySEO } from '../seo';
import { loadYmaps } from '../lib/ymaps';

export default function PharmacyDetail() {
  const { id, city: cityParam } = useParams();
  const { city, cities, setCity } = useCity();
  const [ph, setPh] = useState(null);
  const [notFound, setNotFound] = useState(false);
  const ref = useRef(null);
  const mapRef = useRef(null);

  useEffect(() => {
    if (cityParam && cities) {
      const f = cities.find(c => c.id === cityParam);
      if (f && f.id !== city.id) setCity(f);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cityParam]);

  useEffect(() => {
    setPh(null);
    setNotFound(false);
    fetchPharmacy(id)
      .then(setPh)
      .catch((e) => setNotFound(e?.response?.status === 404));
  }, [id]);

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

  if (notFound) return (
    <div className="max-w-7xl mx-auto px-4 py-16 text-center">
      <h1 className="text-2xl font-bold mb-2">Аптека не найдена</h1>
      <Link to={`/${city.id}/apteki`} className="text-emerald-700 hover:underline">К списку аптек</Link>
    </div>
  );
  if (!ph) {
    return <div className="max-w-7xl mx-auto px-4 py-16 text-center text-slate-500">Загрузка аптеки…</div>;
  }

  const seo = pharmacySEO(city.id, ph);
  const routeHref = `https://yandex.ru/maps/?rtext=~${ph.lat}%2C${ph.lng}&rtt=auto&z=15`;

  const pharmacyJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'Pharmacy',
    name: ph.name,
    address: { '@type': 'PostalAddress', streetAddress: ph.address, addressLocality: city.name, addressCountry: 'RU' },
    telephone: ph.phone,
    openingHours: ph.hours,
    geo: { '@type': 'GeoCoordinates', latitude: ph.lat, longitude: ph.lng },
  };

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <SEOHead seo={{ ...seo, jsonLd: pharmacyJsonLd }} />
      <nav className="text-xs text-slate-500 mb-4 flex items-center gap-1.5">
        <Link to={`/${city.id}`} className="hover:text-emerald-700">Главная</Link>
        <ChevronRight className="w-3 h-3" />
        <Link to={`/${city.id}/apteki`} className="hover:text-emerald-700">Аптеки</Link>
        <ChevronRight className="w-3 h-3" />
        <span>{ph.name}</span>
      </nav>

      <div className="grid lg:grid-cols-[1fr_400px] gap-6 mb-10">
        <div>
          <h1 className="text-3xl md:text-4xl font-bold text-slate-900">{ph.name}</h1>
          <div className="flex items-center gap-3 mt-2 text-sm text-slate-500">
            <span>Сеть: <span className="text-slate-700 font-medium">{ph.chain}</span></span>
            {ph.rating && (
              <span className="inline-flex items-center gap-1 text-amber-700"><Star className="w-3.5 h-3.5 fill-amber-400 text-amber-400" /> {ph.rating}</span>
            )}
          </div>
          <div className="mt-5 grid sm:grid-cols-3 gap-3">
            <div className="bg-slate-50 rounded-lg p-3"><div className="flex items-center gap-1.5 text-[11px] text-slate-500 uppercase tracking-wide"><MapPin className="w-3 h-3" /> Адрес</div><div className="text-sm font-medium text-slate-800 mt-1">{ph.address}</div>{ph.metro && <div className="text-xs text-emerald-700 mt-0.5">м. {ph.metro}</div>}</div>
            <div className="bg-slate-50 rounded-lg p-3"><div className="flex items-center gap-1.5 text-[11px] text-slate-500 uppercase tracking-wide"><Phone className="w-3 h-3" /> Телефон</div><div className="text-sm font-medium text-slate-800 mt-1">{ph.phone}</div></div>
            <div className="bg-slate-50 rounded-lg p-3"><div className="flex items-center gap-1.5 text-[11px] text-slate-500 uppercase tracking-wide"><Clock className="w-3 h-3" /> Режим</div><div className="text-sm font-medium text-slate-800 mt-1">{ph.hours}</div></div>
          </div>
          <a
            data-testid="pharmacy-route-btn"
            href={routeHref}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-5 inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-emerald-200 bg-emerald-50/50 text-emerald-700 hover:bg-emerald-600 hover:text-white hover:border-emerald-600 transition"
          >
            <Navigation className="w-4 h-4" /> Построить маршрут
          </a>
        </div>
        <div ref={ref} className="w-full h-72 lg:h-full rounded-xl overflow-hidden border border-slate-100" />
      </div>

      <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 text-sm text-amber-900">
        <strong>Информация о наличии и ценах</strong> в этой аптеке отображается на страницах конкретных препаратов. Воспользуйтесь поиском, чтобы найти нужное лекарство.
      </div>
    </div>
  );
}
