import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ChevronRight, MapPin, Phone, Clock, Pill, ShieldAlert, Tag } from 'lucide-react';
import { findMedBySlug, PHARMACIES, PRICES, getAnalogs, CATEGORIES } from '../mock';
import { useCity } from '../context/CityContext';
import MedCard from '../components/MedCard';

// Load Yandex Maps JS API once
let ymapsPromise = null;
function loadYmaps() {
  if (ymapsPromise) return ymapsPromise;
  ymapsPromise = new Promise((resolve, reject) => {
    if (window.ymaps) return window.ymaps.ready(() => resolve(window.ymaps));
    const s = document.createElement('script');
    s.src = 'https://api-maps.yandex.ru/2.1/?lang=ru_RU';
    s.async = true;
    s.onload = () => window.ymaps.ready(() => resolve(window.ymaps));
    s.onerror = reject;
    document.head.appendChild(s);
  });
  return ymapsPromise;
}

function PriceMap({ med, prices, pharmacies, cityCenter, onSelect, selected }) {
  const ref = useRef(null);
  const mapRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    loadYmaps().then((ymaps) => {
      if (cancelled) return;
      if (mapRef.current) {
        mapRef.current.destroy();
        mapRef.current = null;
      }
      const map = new ymaps.Map(ref.current, {
        center: cityCenter,
        zoom: 11,
        controls: ['zoomControl', 'fullscreenControl', 'geolocationControl'],
      }, { suppressMapOpenBlock: true });
      mapRef.current = map;

      const PriceLayout = ymaps.templateLayoutFactory.createClass(
        '<div class="ymap-price-pill">{{ properties.price }} ₽</div>',
        {
          build: function () {
            PriceLayout.superclass.build.call(this);
            const el = this.getParentElement().querySelector('.ymap-price-pill');
            if (el) {
              el.addEventListener('click', () => {
                const pid = this.getData().properties.get('pid');
                onSelect && onSelect(pid);
              });
            }
          }
        }
      );

      const placemarks = prices.map(pr => {
        const ph = pharmacies.find(p => p.id === pr.pharmacyId);
        if (!ph) return null;
        return new ymaps.Placemark([ph.lat, ph.lng], {
          price: pr.price,
          pid: ph.id,
          balloonContent: `<strong>${ph.name}</strong><br/>${ph.address}<br/><b>${pr.price} ₽</b> · в наличии: ${pr.qty} шт.<br/>${ph.phone}`,
        }, {
          iconLayout: PriceLayout,
          iconShape: { type: 'Rectangle', coordinates: [[-50, -50], [50, 0]] },
        });
      }).filter(Boolean);

      placemarks.forEach(p => map.geoObjects.add(p));
      if (placemarks.length) {
        map.setBounds(map.geoObjects.getBounds(), { checkZoomRange: true, zoomMargin: 50 });
      }
    }).catch((e) => console.error('Ymaps load error', e));
    return () => {
      cancelled = true;
      if (mapRef.current) { mapRef.current.destroy(); mapRef.current = null; }
    };
    // eslint-disable-next-line
  }, [med.slug, cityCenter[0], cityCenter[1], prices.length]);

  return <div ref={ref} className="w-full h-[460px] rounded-xl overflow-hidden border border-slate-100" />;
}

export default function MedDetail() {
  const { slug } = useParams();
  const med = findMedBySlug(slug);
  const { city } = useCity();
  const [selectedId, setSelectedId] = useState(null);

  const cat = med ? CATEGORIES.find(c => c.slug === med.category) : null;

  const prices = useMemo(() => {
    if (!med) return [];
    const list = [...(PRICES[med.slug]?.[city.id] || [])];
    list.sort((a, b) => a.price - b.price);
    return list;
  }, [med, city.id]);

  const cityPharms = PHARMACIES.filter(p => p.city === city.id);
  const cityCenter = city.center;

  if (!med) return (
    <div className="max-w-7xl mx-auto px-4 py-16 text-center">
      <h1 className="text-2xl font-bold mb-2">Препарат не найден</h1>
      <Link to="/preparaty" className="text-emerald-700 hover:underline">К каталогу</Link>
    </div>
  );

  const minPrice = Math.min(...prices.map(p => p.price));
  const maxPrice = Math.max(...prices.map(p => p.price));
  const analogs = getAnalogs(med);

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <nav className="text-xs text-slate-500 mb-4 flex items-center flex-wrap gap-x-1.5">
        <Link to="/" className="hover:text-emerald-700">Главная</Link>
        <ChevronRight className="w-3 h-3" />
        <Link to="/preparaty" className="hover:text-emerald-700">Каталог</Link>
        {cat && <><ChevronRight className="w-3 h-3" /><Link to={`/kategorii/${cat.slug}`} className="hover:text-emerald-700">{cat.title}</Link></>}
        <ChevronRight className="w-3 h-3" /><span className="text-slate-700">{med.name}</span>
      </nav>

      <div className="grid lg:grid-cols-[380px_1fr] gap-8 mb-10">
        <div className="bg-white border border-slate-100 rounded-2xl p-6">
          <div className="aspect-square rounded-xl bg-slate-50 overflow-hidden flex items-center justify-center">
            {med.image ? <img src={med.image} alt={med.name} className="w-full h-full object-cover" /> : <Pill className="w-16 h-16 text-emerald-300" />}
          </div>
        </div>
        <div>
          {med.rx && (
            <div className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide bg-rose-50 text-rose-700 px-2.5 py-1 rounded mb-3">
              <ShieldAlert className="w-3.5 h-3.5" /> Отпуск по рецепту
            </div>
          )}
          <h1 className="text-3xl md:text-4xl font-bold text-slate-900">{med.name}</h1>
          <p className="text-slate-600 mt-1.5">{med.form}, {med.pack}</p>

          <div className="mt-5 grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
            <div className="bg-slate-50 rounded-lg p-3"><div className="text-[11px] text-slate-500 uppercase tracking-wide">Производитель</div><div className="font-medium text-slate-800">{med.manufacturer}</div></div>
            <div className="bg-slate-50 rounded-lg p-3"><div className="text-[11px] text-slate-500 uppercase tracking-wide">Страна</div><div className="font-medium text-slate-800">{med.country}</div></div>
            <div className="bg-slate-50 rounded-lg p-3"><div className="text-[11px] text-slate-500 uppercase tracking-wide">МНН</div><div className="font-medium text-slate-800">{med.mnn}</div></div>
          </div>

          <div className="mt-6 bg-emerald-50/60 border border-emerald-100 rounded-xl p-5">
            <div className="flex items-end gap-4">
              <div>
                <div className="text-xs text-emerald-800/80">Минимальная цена в {city.inLoc}</div>
                <div className="text-3xl font-extrabold text-emerald-700">{minPrice} ₽</div>
              </div>
              <div className="text-sm text-slate-600 pb-1">до {maxPrice} ₽ · в {prices.length} аптеках</div>
            </div>
            <p className="legal-band mt-3">Сведения о ценах и остатках носят справочный характер. Не является публичной офертой.</p>
          </div>
        </div>
      </div>

      {/* Map block */}
      <section className="mb-10">
        <div className="flex items-end justify-between mb-3">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">{med.name} на карте — {city.name}</h2>
            <p className="text-sm text-slate-500 mt-1">Нажмите на облачко с ценой, чтобы увидеть адрес и наличие</p>
          </div>
        </div>
        <PriceMap med={med} prices={prices} pharmacies={cityPharms} cityCenter={cityCenter} onSelect={setSelectedId} selected={selectedId} />
      </section>

      {/* Prices list */}
      <section className="mb-12">
        <div className="flex items-end justify-between mb-4">
          <h2 className="text-2xl font-bold text-slate-900">Цены в аптеках</h2>
          <div className="text-sm text-slate-500">Сортировка: сначала дешевле</div>
        </div>
        <div className="bg-white border border-slate-100 rounded-xl divide-y divide-slate-100 overflow-hidden">
          {prices.map(pr => {
            const ph = PHARMACIES.find(p => p.id === pr.pharmacyId);
            if (!ph) return null;
            return (
              <div key={pr.pharmacyId} className={`grid grid-cols-[1fr_auto] sm:grid-cols-[1fr_120px_140px_120px] items-center gap-3 px-4 py-3 hover:bg-emerald-50/30 transition ${selectedId === ph.id ? 'bg-emerald-50/50' : ''}`}>
                <div>
                  <Link to={`/apteki/${ph.id}`} className="font-semibold text-slate-900 hover:text-emerald-700">{ph.name}</Link>
                  <div className="text-xs text-slate-500 mt-0.5 flex items-center gap-1.5"><MapPin className="w-3.5 h-3.5" /> {ph.address}{ph.metro && <span className="text-emerald-600"> · м. {ph.metro}</span>}</div>
                </div>
                <div className="hidden sm:flex items-center gap-1.5 text-xs text-slate-500"><Clock className="w-3.5 h-3.5" /> {ph.hours}</div>
                <div className="hidden sm:flex items-center gap-1.5 text-xs text-slate-500"><Phone className="w-3.5 h-3.5" /> {ph.phone}</div>
                <div className="text-right">
                  <div className="text-lg font-bold text-emerald-700">{pr.price} ₽</div>
                  <div className="text-[11px] text-slate-500">в наличии: {pr.qty} шт</div>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Description */}
      <section className="grid lg:grid-cols-2 gap-6 mb-12">
        <div className="bg-white border border-slate-100 rounded-xl p-6">
          <h2 className="text-xl font-bold text-slate-900 mb-3">О препарате</h2>
          <p className="text-slate-700 leading-relaxed">{med.description}</p>
          <h3 className="font-semibold text-slate-900 mt-5 mb-2 text-sm uppercase tracking-wide">Показания</h3>
          <ul className="text-slate-700 space-y-1 text-sm list-disc list-inside marker:text-emerald-500">
            {med.indications.map(x => <li key={x}>{x}</li>)}
          </ul>
        </div>
        <div className="bg-white border border-slate-100 rounded-xl p-6">
          <h2 className="text-xl font-bold text-slate-900 mb-3">Противопоказания</h2>
          <ul className="text-slate-700 space-y-1 text-sm list-disc list-inside marker:text-rose-400">
            {med.contraindications.map(x => <li key={x}>{x}</li>)}
          </ul>
          <h3 className="font-semibold text-slate-900 mt-5 mb-2 text-sm uppercase tracking-wide">Хранение</h3>
          <p className="text-slate-700 text-sm">{med.storage}</p>
          <div className="mt-5 p-3 bg-amber-50 border border-amber-200 rounded-lg flex items-start gap-2">
            <ShieldAlert className="w-4 h-4 text-amber-700 shrink-0 mt-0.5" />
            <p className="text-xs text-amber-900">Имеются противопоказания. Перед применением обязательно проконсультируйтесь с врачом.</p>
          </div>
        </div>
      </section>

      {/* Analogs */}
      {analogs.length > 0 && (
        <section className="mb-12">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-9 h-9 rounded-lg bg-emerald-50 text-emerald-700 flex items-center justify-center"><Tag className="w-5 h-5" /></div>
            <h2 className="text-2xl font-bold text-slate-900">Аналоги и похожие препараты</h2>
          </div>
          <div className="grid sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {analogs.map(a => <MedCard key={a.slug} med={a} />)}
          </div>
        </section>
      )}
    </div>
  );
}
