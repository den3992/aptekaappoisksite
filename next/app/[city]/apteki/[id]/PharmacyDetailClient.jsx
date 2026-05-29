'use client';
import React, { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { MapPin, Phone, Clock, ChevronRight, Star, Navigation } from 'lucide-react';
import { useCity } from '../../../../context/CityContext';
import { fetchPharmacy } from '../../../../api/client';
import { loadYmaps } from '../../../../lib/ymaps';

export default function PharmacyDetail({ initialPh = null }) {
  const { id, city: cityParam } = useParams();
  const { city, cities, setCity } = useCity();
  const [ph, setPh] = useState(initialPh);
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
    // С initialPh от SSR — спиннер на первом маунте не нужен.
    // Сбрасываем ph только если id поменялся И initialPh не для этого id.
    if (!ph || ph?.id !== id) setPh(null);
    setNotFound(false);
    fetchPharmacy(id)
      .then(setPh)
      .catch((e) => setNotFound(e?.response?.status === 404));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    if (!ph) return;
    // Нет координат (напр. сетевая запись «Горздрав») → карту не строим,
    // иначе ymaps.Map с center:[null,null] рисует пустой серый тайл.
    if (!Number.isFinite(ph.lat) || !Number.isFinite(ph.lng)) return;
    let cancelled = false;
    loadYmaps().then(ymaps => {
      if (cancelled) return;
      if (mapRef.current) { mapRef.current.destroy(); mapRef.current = null; }
      const m = new ymaps.Map(ref.current, { center: [ph.lat, ph.lng], zoom: 15, controls: ['zoomControl'] }, { suppressMapOpenBlock: true });
      const placemark = new ymaps.Placemark([ph.lat, ph.lng], {
        balloonContent: `<strong>${ph.name}</strong><br/>${ph.address}<br/><a href="tel:${(ph.phone || '').replace(/[^+\d]/g, '')}">${ph.phone || ''}</a>`,
      }, { preset: 'islands#greenIcon' });
      m.geoObjects.add(placemark);
      mapRef.current = m;
    });
    return () => { cancelled = true; if (mapRef.current) { mapRef.current.destroy(); mapRef.current = null; } };
  }, [ph]);

  if (notFound) return (
    <div className="max-w-7xl mx-auto px-4 py-16 text-center">
      <h1 className="text-2xl font-bold mb-2">Аптека не найдена</h1>
      <Link href={`/${city.id}/apteki`} className="text-emerald-700 hover:underline">К списку аптек</Link>
    </div>
  );
  if (!ph) {
    return <div className="max-w-7xl mx-auto px-4 py-16 text-center text-slate-500">Загрузка аптеки…</div>;
  }

  const hasCoords = Number.isFinite(ph.lat) && Number.isFinite(ph.lng);
  const routeHref = hasCoords ? `https://yandex.ru/maps/?rtext=~${ph.lat}%2C${ph.lng}&rtt=auto&z=15` : null;
  const telHref = `tel:${(ph.phone || "").replace(/[^+\d]/g, "")}`;

  const pharmacyJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'Pharmacy',
    name: ph.name,
    address: { '@type': 'PostalAddress', streetAddress: ph.address, addressLocality: city.name, addressCountry: 'RU' },
    telephone: ph.phone,
    openingHours: ph.hours,
    ...(hasCoords ? { geo: { '@type': 'GeoCoordinates', latitude: ph.lat, longitude: ph.lng } } : {}),
  };

  return (
    <div className="max-w-7xl mx-auto px-4 py-5 md:py-8 pb-32 md:pb-8" data-testid="pharmacy-detail-page">
      
      <nav className="text-xs text-slate-500 mb-3 md:mb-4 flex items-center gap-1.5 flex-wrap">
        <Link href={`/${city.id}`} className="hover:text-emerald-700">Главная</Link>
        <ChevronRight className="w-3 h-3 shrink-0" />
        <Link href={`/${city.id}/apteki`} className="hover:text-emerald-700">Аптеки</Link>
        <ChevronRight className="w-3 h-3 shrink-0" />
        <span className="line-clamp-1">{ph.name}</span>
      </nav>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_400px] gap-5 lg:gap-6 mb-8 md:mb-10">
        {/* Header (H1 + meta line) — order 1 on both */}
        <div className="order-1 lg:order-1 lg:col-start-1">
          <h1 className="text-2xl sm:text-3xl md:text-4xl font-bold text-slate-900 leading-tight" data-testid="pharmacy-h1">{ph.name}</h1>
          <div className="flex items-center gap-3 mt-2 text-sm text-slate-500 flex-wrap">
            <span>Сеть: <span className="text-slate-700 font-medium">{ph.chain}</span></span>
            {ph.rating && (
              <span className="inline-flex items-center gap-1 text-amber-700"><Star className="w-3.5 h-3.5 fill-amber-400 text-amber-400" /> {ph.rating}</span>
            )}
          </div>
        </div>

        {/* Map — на mobile order-2 (сразу после H1), на desktop order-3 + col-2 + row-span-2.
            Карту строим только при наличии координат; у сетевых записей (Горздрав)
            их нет — показываем плейсхолдер вместо пустого серого тайла. */}
        {hasCoords ? (
          <div
            ref={ref}
            className="order-2 lg:order-3 lg:row-span-2 lg:col-start-2 w-full h-64 lg:h-full rounded-xl overflow-hidden border border-slate-100"
            data-testid="pharmacy-map"
          />
        ) : (
          <div
            className="order-2 lg:order-3 lg:row-span-2 lg:col-start-2 w-full h-64 lg:h-full rounded-xl border border-slate-100 bg-slate-50 flex flex-col items-center justify-center text-center px-6"
            data-testid="pharmacy-map-placeholder"
          >
            <MapPin className="w-8 h-8 text-slate-300 mb-2" />
            <p className="text-sm text-slate-500">Сеть аптек — единой точки на карте нет. Наличие смотрите на странице препарата.</p>
            {ph.url && (
              <a href={ph.url} target="_blank" rel="noopener noreferrer" className="mt-3 text-sm font-medium text-emerald-700 hover:underline">
                Сайт сети
              </a>
            )}
          </div>
        )}

        {/* Meta cards + desktop CTA — on mobile order-3, on desktop order-2 (col-1, below H1) */}
        <div className="order-3 lg:order-2 lg:col-start-1">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {hasCoords ? (
              <a
                href={routeHref}
                target="_blank"
                rel="noopener noreferrer"
                className="bg-slate-50 rounded-lg p-3 active:bg-slate-100 hover:bg-slate-100 transition"
              >
                <div className="flex items-center gap-1.5 text-[11px] text-slate-500 uppercase tracking-wide"><MapPin className="w-3 h-3" /> Адрес</div>
                <div className="text-sm font-medium text-slate-800 mt-1">{ph.address}</div>
                {ph.metro && <div className="text-xs text-emerald-700 mt-0.5">м. {ph.metro}</div>}
              </a>
            ) : (
              <div className="bg-slate-50 rounded-lg p-3">
                <div className="flex items-center gap-1.5 text-[11px] text-slate-500 uppercase tracking-wide"><MapPin className="w-3 h-3" /> Адрес</div>
                <div className="text-sm font-medium text-slate-800 mt-1">{ph.address}</div>
                {ph.metro && <div className="text-xs text-emerald-700 mt-0.5">м. {ph.metro}</div>}
              </div>
            )}
            {ph.phone && (
              <a
                href={telHref}
                data-testid="pharmacy-phone-link"
                className="bg-slate-50 rounded-lg p-3 active:bg-slate-100 hover:bg-slate-100 transition"
              >
                <div className="flex items-center gap-1.5 text-[11px] text-slate-500 uppercase tracking-wide"><Phone className="w-3 h-3" /> Телефон</div>
                <div className="text-sm font-medium text-slate-800 mt-1 hover:text-emerald-700">{ph.phone}</div>
              </a>
            )}
            {ph.hours && (
              <div className="bg-slate-50 rounded-lg p-3">
                <div className="flex items-center gap-1.5 text-[11px] text-slate-500 uppercase tracking-wide"><Clock className="w-3 h-3" /> Режим</div>
                <div className="text-sm font-medium text-slate-800 mt-1">{ph.hours}</div>
              </div>
            )}
          </div>

          {/* Desktop route button (mobile uses sticky CTAs below) — только при координатах */}
          {hasCoords && (
            <a
              data-testid="pharmacy-route-btn"
              href={routeHref}
              target="_blank"
              rel="noopener noreferrer"
              className="hidden md:inline-flex mt-5 items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-emerald-200 bg-emerald-50/50 text-emerald-700 hover:bg-emerald-600 hover:text-white hover:border-emerald-600 transition"
            >
              <Navigation className="w-4 h-4" /> Построить маршрут
            </a>
          )}
        </div>
      </div>

      <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 md:p-5 text-sm text-amber-900">
        <strong>Информация о наличии и ценах</strong> в этой аптеке отображается на страницах конкретных препаратов. Воспользуйтесь поиском, чтобы найти нужное лекарство.
      </div>

      {/* Sticky mobile CTAs: phone + route (above tab-bar) — скрываем кнопки,
          для которых нет данных (у сети нет телефона/координат). */}
      {(ph.phone || hasCoords) && (
        <div
          className="md:hidden fixed left-0 right-0 z-30 px-4 pointer-events-none flex gap-2"
          style={{ bottom: 'calc(64px + env(safe-area-inset-bottom) + 8px)' }}
          data-testid="pharmacy-mobile-cta-wrap"
        >
          {ph.phone && (
            <a
              href={telHref}
              data-testid="pharmacy-mobile-phone"
              className="pointer-events-auto flex-1 h-12 rounded-xl bg-white border border-slate-200 text-slate-800 font-semibold shadow-lg flex items-center justify-center gap-2 active:bg-slate-50"
            >
              <Phone className="w-4 h-4 text-emerald-600" /> Позвонить
            </a>
          )}
          {hasCoords && (
            <a
              href={routeHref}
              target="_blank"
              rel="noopener noreferrer"
              data-testid="pharmacy-mobile-route"
              className="pointer-events-auto flex-1 h-12 rounded-xl bg-emerald-600 text-white font-semibold shadow-lg shadow-emerald-600/20 flex items-center justify-center gap-2 active:bg-emerald-700"
            >
              <Navigation className="w-4 h-4" /> Маршрут
            </a>
          )}
        </div>
      )}
    </div>
  );
}
