import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ChevronRight, MapPin, Phone, Clock, Pill, ShieldAlert, Tag, Navigation } from 'lucide-react';
import { useCity } from '../context/CityContext';
import { fetchMed, fetchAnalogs, fetchPharmacies } from '../api/client';
import SEOHead from '../components/SEOHead';
import { medSEO } from '../seo';
import { loadYmaps } from '../lib/ymaps';

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
        const ph = pharmacies.find(p => p.id === pr.pharmacy_id);
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
  }, [med?.slug, cityCenter[0], cityCenter[1], prices.length]);

  return <div ref={ref} className="w-full h-[460px] rounded-xl overflow-hidden border border-slate-100" />;
}

export default function MedDetail() {
  const { slug, city: cityParam } = useParams();
  const { city, cities, setCity } = useCity();
  const [selectedId, setSelectedId] = useState(null);
  const [med, setMed] = useState(null);
  const [analogs, setAnalogs] = useState([]);
  const [pharmacies, setPharmacies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  // Sync URL city → context
  useEffect(() => {
    if (cityParam && cities) {
      const found = cities.find(c => c.id === cityParam);
      if (found && found.id !== city.id) setCity(found);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cityParam]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setNotFound(false);
    Promise.all([fetchMed(slug), fetchAnalogs(slug, 8), fetchPharmacies(city.id)])
      .then(([m, a, ph]) => {
        if (cancelled) return;
        setMed(m);
        setAnalogs(a);
        setPharmacies(ph);
      })
      .catch((e) => {
        if (!cancelled) {
          setNotFound(e?.response?.status === 404);
          setMed(null);
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [slug, city.id]);

  const prices = useMemo(() => {
    if (!med) return [];
    const list = [...((med.prices_by_city || {})[city.id] || [])];
    list.sort((a, b) => a.price - b.price);
    return list;
  }, [med, city.id]);

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-16 text-center text-slate-500">Загрузка препарата…</div>
    );
  }

  if (notFound || !med) return (
    <div className="max-w-7xl mx-auto px-4 py-16 text-center">
      <h1 className="text-2xl font-bold mb-2">Препарат не найден</h1>
      <Link to={`/${city.id}/preparaty`} className="text-emerald-700 hover:underline">К каталогу</Link>
    </div>
  );

  const minPrice = prices.length ? Math.min(...prices.map(p => p.price)) : null;
  const maxPrice = prices.length ? Math.max(...prices.map(p => p.price)) : null;
  const seo = medSEO(city.id, med);
  const formLower = (med.form || '').toLowerCase();

  // Schema.org Drug
  const drugJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'Drug',
    name: med.name,
    nonProprietaryName: med.mnn || undefined,
    manufacturer: med.manufacturer ? { '@type': 'Organization', name: med.manufacturer } : undefined,
    dosageForm: formLower || undefined,
    description: seo.description,
    prescriptionStatus: med.rx ? 'PrescriptionOnly' : 'OTC',
    url: seo.canonical,
  };

  return (
    <div className="max-w-7xl mx-auto px-4 py-8" data-testid="med-detail-page">
      <SEOHead seo={{ ...seo, jsonLd: drugJsonLd }} />

      <nav className="text-xs text-slate-500 mb-4 flex items-center flex-wrap gap-x-1.5">
        <Link to={`/${city.id}`} className="hover:text-emerald-700">Главная</Link>
        <ChevronRight className="w-3 h-3" />
        <Link to={`/${city.id}/preparaty`} className="hover:text-emerald-700">Каталог</Link>
        {med.category && med.category !== 'other' && (
          <>
            <ChevronRight className="w-3 h-3" />
            <Link to={`/${city.id}/kategorii/${med.category}`} className="hover:text-emerald-700 capitalize">{med.category.replace(/-/g, ' ')}</Link>
          </>
        )}
        <ChevronRight className="w-3 h-3" /><span className="text-slate-700">{med.name}</span>
      </nav>

      <div className="grid lg:grid-cols-[380px_1fr] gap-8 mb-10">
        <div className="bg-white border border-slate-100 rounded-2xl p-6">
          <div className="aspect-square rounded-xl bg-slate-50 overflow-hidden flex items-center justify-center">
            {med.image_url ? (
              <img
                src={med.image_url}
                alt={[med.name, med.dosage, med.form].filter(Boolean).join(", ")}
                className="max-w-full max-h-full object-contain p-4"
                loading="eager"
                data-testid="med-image"
              />
            ) : (
              <Pill className="w-24 h-24 text-emerald-300" />
            )}
          </div>
        </div>
        <div>
          <div className="flex flex-wrap gap-1.5 mb-3">
            {med.rx && (
              <div className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide bg-rose-50 text-rose-700 px-2.5 py-1 rounded">
                <ShieldAlert className="w-3.5 h-3.5" /> Отпускается по рецепту
              </div>
            )}
          </div>
          <h1 className="text-3xl md:text-4xl font-bold text-slate-900">{med.name}</h1>
          <p className="text-slate-600 mt-1.5">{[formLower, med.dosage].filter(Boolean).join(', ')}</p>

          <div className="mt-5 grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
            <div className="bg-slate-50 rounded-lg p-3"><div className="text-[11px] text-slate-500 uppercase tracking-wide">Производитель</div><div className="font-medium text-slate-800">{med.manufacturer || '—'}</div></div>
            <div className="bg-slate-50 rounded-lg p-3"><div className="text-[11px] text-slate-500 uppercase tracking-wide">Страна</div><div className="font-medium text-slate-800">{med.manufacturer_country || '—'}</div></div>
            {med.mnn && <div className="bg-slate-50 rounded-lg p-3"><div className="text-[11px] text-slate-500 uppercase tracking-wide">МНН</div><div className="font-medium text-slate-800">{med.mnn.toLowerCase()}</div></div>}
          </div>

          {minPrice !== null && (
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
          )}
        </div>
      </div>

      {/* Map */}
      {prices.length > 0 && (
        <section className="mb-10">
          <div className="flex items-end justify-between mb-3">
            <div>
              <h2 className="text-2xl font-bold text-slate-900">{med.name} на карте — {city.name}</h2>
              <p className="text-sm text-slate-500 mt-1">Нажмите на облачко с ценой, чтобы увидеть адрес и наличие</p>
            </div>
          </div>
          <PriceMap med={med} prices={prices} pharmacies={pharmacies} cityCenter={city.center} onSelect={setSelectedId} selected={selectedId} />
        </section>
      )}

      {/* Prices list */}
      {prices.length > 0 && (
        <section className="mb-12">
          <div className="flex items-end justify-between mb-4">
            <h2 className="text-2xl font-bold text-slate-900">Цены в аптеках</h2>
            <div className="text-sm text-slate-500">Сортировка: сначала дешевле</div>
          </div>
          <div className="bg-white border border-slate-100 rounded-xl divide-y divide-slate-100 overflow-hidden">
            {prices.map(pr => {
              const ph = pharmacies.find(p => p.id === pr.pharmacy_id);
              if (!ph) return null;
              return (
                <div key={pr.pharmacy_id} className={`grid grid-cols-[1fr_auto] sm:grid-cols-[1fr_120px_140px_120px_140px] items-center gap-3 px-4 py-3 hover:bg-emerald-50/30 transition ${selectedId === ph.id ? 'bg-emerald-50/50' : ''}`}>
                  <div>
                    <Link to={`/${city.id}/apteki/${ph.id}`} className="font-semibold text-slate-900 hover:text-emerald-700">{ph.name}</Link>
                    <div className="text-xs text-slate-500 mt-0.5 flex items-center gap-1.5"><MapPin className="w-3.5 h-3.5" /> {ph.address}{ph.metro && <span className="text-emerald-600"> · м. {ph.metro}</span>}</div>
                  </div>
                  <div className="hidden sm:flex items-center gap-1.5 text-xs text-slate-500"><Clock className="w-3.5 h-3.5" /> {ph.hours}</div>
                  <div className="hidden sm:flex items-center gap-1.5 text-xs text-slate-500"><Phone className="w-3.5 h-3.5" /> {ph.phone}</div>
                  <div className="text-right">
                    <div className="text-lg font-bold text-emerald-700">{pr.price} ₽</div>
                    <div className="text-[11px] text-slate-500">в наличии: {pr.qty} шт</div>
                  </div>
                  <a
                    data-testid="route-btn"
                    href={`https://yandex.ru/maps/?rtext=~${ph.lat}%2C${ph.lng}&rtt=auto&z=15`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hidden sm:inline-flex items-center justify-center gap-1.5 text-xs font-medium px-3 py-2 rounded-lg border border-emerald-200 bg-emerald-50/50 text-emerald-700 hover:bg-emerald-600 hover:text-white hover:border-emerald-600 transition whitespace-nowrap"
                    title="Открыть маршрут в Яндекс.Картах"
                  >
                    <Navigation className="w-3.5 h-3.5" /> Маршрут
                  </a>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* LLM-enriched description (top-200 popular meds) */}
      {med.enrichment && (
        <section className="mb-12" data-testid="enrichment-section">
          <div className="bg-white border border-slate-100 rounded-2xl p-6 md:p-8">
            <h2 className="text-2xl font-bold text-slate-900 mb-3">О препарате</h2>
            {med.enrichment.summary && (
              <p className="text-slate-700 leading-relaxed mb-6">{med.enrichment.summary}</p>
            )}
            <div className="grid md:grid-cols-2 gap-6">
              {med.enrichment.indications?.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-emerald-800 uppercase tracking-wide mb-2">Показания</h3>
                  <ul className="space-y-1.5 text-sm text-slate-700">
                    {med.enrichment.indications.map((t, i) => (
                      <li key={i} className="flex gap-2"><span className="text-emerald-500 shrink-0">•</span><span>{t}</span></li>
                    ))}
                  </ul>
                </div>
              )}
              {med.enrichment.contraindications?.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-rose-800 uppercase tracking-wide mb-2">Противопоказания</h3>
                  <ul className="space-y-1.5 text-sm text-slate-700">
                    {med.enrichment.contraindications.map((t, i) => (
                      <li key={i} className="flex gap-2"><span className="text-rose-500 shrink-0">•</span><span>{t}</span></li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            {med.enrichment.how_to_take && (
              <div className="mt-6 pt-6 border-t border-slate-100">
                <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-2">Способ применения</h3>
                <p className="text-sm text-slate-700 leading-relaxed">{med.enrichment.how_to_take}</p>
              </div>
            )}
            <p className="mt-5 text-xs text-slate-500 italic">
              Справочная информация. {med.enrichment.disclaimer || 'Имеются противопоказания. Перед применением проконсультируйтесь с врачом.'}
            </p>
          </div>
        </section>
      )}

      {/* Disclaimer */}
      <section className="mb-12">
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 flex items-start gap-3">
          <ShieldAlert className="w-5 h-5 text-amber-700 shrink-0 mt-0.5" />
          <div className="text-sm text-amber-900">
            <strong>Имеются противопоказания.</strong> Информация на странице носит справочный характер и не является
            рекомендацией к применению. Перед приёмом препарата обязательно проконсультируйтесь с врачом или фармацевтом.
          </div>
        </div>
      </section>

      {/* Analogs */}
      {analogs.length > 0 && (
        <section className="mb-12" data-testid="analogs-section">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-9 h-9 rounded-lg bg-emerald-50 text-emerald-700 flex items-center justify-center"><Tag className="w-5 h-5" /></div>
            <h2 className="text-2xl font-bold text-slate-900">Аналоги по МНН: {med.mnn ? med.mnn.toLowerCase() : '—'}</h2>
          </div>
          <div className="grid sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {analogs.map(a => (
              <Link
                key={a.slug}
                to={`/${city.id}/preparaty/${a.slug}`}
                className="bg-white border border-slate-100 rounded-xl p-3 hover:border-emerald-300 transition"
              >
                {a.rx && (
                  <span className="inline-block text-[10px] font-semibold uppercase tracking-wide bg-rose-50 text-rose-700 px-2 py-0.5 rounded mb-1.5">
                    Отпускается по рецепту
                  </span>
                )}
                <h3 className="font-semibold text-slate-900 text-sm leading-tight line-clamp-2">{a.name}</h3>
                <p className="text-[11px] text-slate-500 mt-1 line-clamp-1">{[a.form?.toLowerCase(), a.dosage].filter(Boolean).join(', ')}</p>
                <p className="text-[11px] text-slate-400 mt-1">{a.manufacturer}</p>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
