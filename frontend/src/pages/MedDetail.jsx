import { formatName, formatManufacturer } from "../utils/text";
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ChevronRight, MapPin, Phone, Clock, Pill, ShieldAlert, Tag, Navigation } from 'lucide-react';
import { useCity } from '../context/CityContext';
import { fetchMed, fetchAnalogs, fetchPharmacies } from '../api/client';
import SEOHead from '../components/SEOHead';
import { medSEO } from '../seo';
import { loadYmaps } from '../lib/ymaps';

// Capitalize first letter, lowercase the rest.
function titleCase(s) {
  if (!s) return '';
  const t = String(s).trim();
  return t.charAt(0).toUpperCase() + t.slice(1).toLowerCase();
}

// Replace clunky/official country names with common usage.
const COUNTRY_NORMALIZE = {
  'соединенное королевство': 'Великобритания',
  'соединенные штаты': 'США',
  'чешская республика': 'Чехия',
  'республика северная македония': 'Северная Македония',
  'македония': 'Северная Македония',
  'киргизская республика': 'Киргизия',
  'южно-африканская республика': 'ЮАР',
  'объединенные арабские эмираты': 'ОАЭ',
  'сан марино': 'Сан-Марино',
  'корея': 'Южная Корея'
};
function normalizeCountry(s) {
  if (!s) return '';
  const key = String(s).trim().toLowerCase();
  return COUNTRY_NORMALIZE[key] || titleCase(s);
}

// Normalize pack_size text to a short user-facing label.
// Examples:
//   "3 × 10 шт"      -> "30 шт"
//   "3 x УПАКОВКА ЯЧЕЙКОВАЯ КОНТУРНАЯ по 10 шт"  -> "30 шт"
//   "№20" / "20 шт"  -> "20 шт"
//   "ТУБА по 50 г"   -> "50 г"
//   "ФЛАКОН 100 мл"  -> "100 мл"
function simplifyPack(s) {
  if (!s) return '';
  // Strip ЕСКЛП encoding artifacts: 'см[3*];^мл' is just 'мл'.
  // Also drop trailing/inline footnote markers and the ';^' field separator.
  let txt = String(s).trim()
    .replace(/\s*см\s*\[3\*\]\s*;?\s*\^?\s*мл/gi, ' мл')
    .replace(/\s*л\s*;\s*\^?\s*дм\s*\[3\*\]/gi, ' л')
    .replace(/м\s*\[3\*\]/gi, 'м³')
    .replace(/\[\*\]/g, '')
    .replace(/;\^/g, ' ')
    .replace(/\bусл\.?\s*ед\b/gi, 'усл.ед.')
    .replace(/\s+/g, ' ')
    .trim();
  // N x <CONTAINER> по M [unit]  →  'N × M <unit>' style.
  // Covers ампулы, флаконы, шприцы, банки, блистеры, упаковки, стрипы, картриджи, тубы.
  let amp = txt.match(/^(\\d+|НЕ УКАЗАНО)\\s*[xх×]\\s*(АМПУЛ\S*|ФЛАКОН\S*|ШПРИЦ\S*|БАНК\S*|БЛИСТЕР\S*|УПАКОВК\S*|СТРИП\S*|КАРТРИДЖ\S*|ТУБ\S*)[^\\d]*\\s*по\\s*(\\d+(?:[\\.,]\\d+)?)\\s*(?:тысяч.?\\s*)?(\\S+)?/i);
  if (amp) {
    const n = amp[1] === 'НЕ УКАЗАНО' ? '1' : amp[1];
    let m = amp[3].replace(',', '.');
    if (m.endsWith('.000')) m = m.slice(0, -4);
    let u = (amp[4] || '').replace(/[.,]/g, '').toLowerCase();
    // common synonyms
    if (u === 'миллиграмм') u = 'мг';
    if (u === 'миллилитр') u = 'мл';
    if (u === 'грамм') u = 'г';
    const unit = ['мл','г','мг','мкг','л','шт'].includes(u) ? u : 'шт';
    txt = `${n} × ${m} ${unit}`;
  }
  // Lone 'CONTAINER по M [unit]' (no leading count) — treat as 1 × M
  else {
    let solo = txt.match(/^(АМПУЛ\S*|ФЛАКОН\S*|ШПРИЦ\S*|БАНК\S*|БЛИСТЕР\S*|УПАКОВК\S*|СТРИП\S*|КАРТРИДЖ\S*|ТУБ\S*)[^\\d]*\\s*по\\s*(\\d+(?:[\\.,]\\d+)?)\\s*(\\S+)?/i);
    if (solo) {
      let m = solo[2].replace(',', '.');
      if (m.endsWith('.000')) m = m.slice(0, -4);
      let u = (solo[3] || '').replace(/[.,]/g, '').toLowerCase();
      if (u === 'миллиграмм') u = 'мг';
      if (u === 'миллилитр') u = 'мл';
      if (u === 'грамм') u = 'г';
      const unit = ['мл','г','мг','мкг','л','шт'].includes(u) ? u : 'шт';
      txt = `${m} ${unit}`;
    }
  }
  // "A × B шт" or "A x B шт"  -> A*B
  let m = txt.match(/(\d+)\s*[×xх]\s*(\d+(?:[\.,]\d+)?)\s*(шт|табл?\.?|капс?\.?|доз\S*|усл\.?\s*ед\.?)/i);
  if (m) {
    const u = m[3].toLowerCase();
    const unit = u.startsWith('доз') ? 'доз' : (u.startsWith('усл') ? 'усл.ед.' : 'шт');
    const total = parseInt(m[1], 10) * parseFloat(m[2].replace(',', '.'));
    const totalStr = Number.isInteger(total) ? String(total) : String(total);
    return `${totalStr} ${unit}`;
  }
  // "по N <unit>" or contains "N <unit>"
  m = txt.match(/(?:по\s+)?(\d+(?:[\.,]\d+)?)\s*(шт|табл?\.?|капс?\.?|доз\S*|усл\.?\s*ед\.?|г|мг|мл|мкг|МЕ|ЕД|м³|%)/i);
  if (m) {
    const v = m[1].replace(',', '.');
    const u = (m[2] || 'шт').toLowerCase().replace(/\./g, '');
    let unit;
    if (u.startsWith('табл') || u.startsWith('капс')) unit = 'шт';
    else if (u.startsWith('доз')) unit = 'доз';
    else if (u.startsWith('усл')) unit = 'усл.ед.';
    else if (m[2] === 'МЕ' || m[2] === 'ЕД') unit = m[2];
    else if (m[2] === 'м³') unit = 'м³';
    else unit = u;
    return `${parseFloat(v) % 1 === 0 ? parseInt(v, 10) : v} ${unit}`;
  }
  // "№20"
  m = txt.match(/№\s*(\d+)/);
  if (m) return `${m[1]} шт`;
  // fallback — just return the original text trimmed and shortened
  return txt.length > 24 ? txt.slice(0, 22) + '…' : txt;
}

// Format a list of pack sizes for compact display.
//   ['10 мл']                    -> '10 мл'
//   ['10 мл', '20 мл']           -> '10 мл, 20 мл'
//   ['15 г', '25 г', '30 г']     -> '15 г, 25 г, 30 г'
//   ['15 г', ..., '150 г'] (>=4) -> '15–150 г (8 шт)'
function formatPackList(items) {
  if (!items || items.length === 0) return '';
  if (items.length <= 3) return items.join(', ');
  // Try to extract numeric value + unit so we can show a range.
  const parsed = items.map(s => {
    const m = String(s).match(/^(\d+(?:\.\d+)?)\s*(.+)$/);
    return m ? { v: parseFloat(m[1]), unit: m[2].trim(), raw: s } : null;
  }).filter(Boolean);
  // Range works only if all share the same unit.
  if (parsed.length === items.length && new Set(parsed.map(p => p.unit)).size === 1) {
    const sorted = [...parsed].sort((a, b) => a.v - b.v);
    const lo = sorted[0].v;
    const hi = sorted[sorted.length - 1].v;
    const unit = parsed[0].unit;
    return `${lo}–${hi} ${unit} (${items.length} шт)`;
  }
  // Heterogeneous units — show first two + count.
  return `${items[0]}, ${items[1]}, … (${items.length} шт)`;
}

// Sort unique pack labels by leading numeric value ascending.
function sortPacks(items) {
  return [...items].sort((a, b) => {
    const na = parseFloat(String(a).match(/^(\d+(?:[\.,]\d+)?)/)?.[1]?.replace(',', '.') || '0');
    const nb = parseFloat(String(b).match(/^(\d+(?:[\.,]\d+)?)/)?.[1]?.replace(',', '.') || '0');
    return na - nb;
  });
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
        const ph = pharmacies.find(p => p.id === pr.pharmacy_id);
        if (!ph) return null;
        return new ymaps.Placemark([ph.lat, ph.lng], {
          price: pr.price,
          pid: ph.id,
          balloonContent: `<strong>${ph.name}</strong><br/>${ph.address}<br/><b>${pr.price} ₽</b> · в наличии: ${pr.qty} шт.<br/><a href="tel:${ph.phone.replace(/[^+\d]/g, '')}">${ph.phone}</a>`,
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
  const [selectedPack, setSelectedPack] = useState(null);
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

  // Unique pack list (computed once per med).
  const packs = useMemo(() => {
    if (!med?.variants) return [];
    return sortPacks([...new Set(med.variants.map(v => simplifyPack(v.pack_size)).filter(Boolean))]);
  }, [med]);

  // Active pack = explicit selection || first pack || null.
  const activePack = selectedPack || packs[0] || null;

  // Parse leading number from pack label ('30 шт' → 30, '50 г' → 50, '1.5 мл' → 1.5).
  function packQty(p) {
    if (!p) return null;
    const m = String(p).match(/^(\d+(?:\.\d+)?)/);
    return m ? parseFloat(m[1]) : null;
  }

  // Deterministic 32-bit hash of a string.
  function hashStr(s) {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    return Math.abs(h);
  }

  const prices = useMemo(() => {
    if (!med) return [];
    const list = [...((med.prices_by_city || {})[city.id] || [])];

    // Scale prices proportionally to active pack vs first pack.
    // Each pack also has a deterministic subset of pharmacies (popular small
    // packs sold in more aptekas; large packs in fewer). This is MOCKED until
    // real per-pack price feeds arrive.
    if (packs.length >= 2 && activePack) {
      const baseQty = packQty(packs[0]) || 1;
      const activeQty = packQty(activePack) || baseQty;
      const ratio = activeQty / baseQty;
      const packSeed = hashStr(med.slug + '|' + activePack);

      // Sublinear scaling: 2× pack ≈ 1.7× price (volume discount).
      const priceFactor = Math.pow(ratio, 0.78);

      // How many of the 12 pharmacies stock this pack: 12 for smallest, ~6 for largest.
      const packIdx = packs.indexOf(activePack);
      const ofMax = packs.length - 1 || 1;
      const stockCount = Math.max(3, Math.round(12 - (packIdx / ofMax) * 6));

      const scaled = list.map((p, i) => {
        // Jitter ±8% per (pharmacy_id × pack) so each pharmacy varies independently.
        const j = ((packSeed + i * 2654435761) >>> 0) % 1000;
        const jitter = 0.92 + (j / 1000) * 0.16;
        const newPrice = Math.max(5, Math.round((p.price * priceFactor * jitter) / 5) * 5);
        const newQty = ((packSeed >>> 1) + i * 16807) % 30 + 1;
        return { ...p, price: newPrice, qty: newQty };
      });

      // Keep top stockCount pharmacies for this pack (deterministic subset).
      const sortedByHash = scaled
        .map((p, i) => ({ p, h: ((packSeed ^ hashStr(p.pharmacy_id)) >>> 0) }))
        .sort((a, b) => a.h - b.h)
        .slice(0, stockCount)
        .map(x => x.p);

      sortedByHash.sort((a, b) => a.price - b.price);
      return sortedByHash;
    }

    list.sort((a, b) => a.price - b.price);
    return list;
  }, [med, city.id, packs, activePack]);

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
        <ChevronRight className="w-3 h-3" /><span className="text-slate-700">{formatName(med.name)}</span>
      </nav>

      <div className="grid lg:grid-cols-[380px_1fr] gap-8 mb-10">
        <div className="bg-white border border-slate-100 rounded-2xl p-6">
          <div className="aspect-square rounded-xl bg-slate-50 overflow-hidden flex items-center justify-center">
            {med.image_url ? (
              <img
                src={med.image_url}
                alt={[formatName(med.name), med.dosage, formatName(med.form)].filter(Boolean).join(", ")}
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
          <h1 className="text-3xl md:text-4xl font-bold text-slate-900" data-testid="med-h1">
            {formatName(med.name)}
            {med.dosage && <span className="text-slate-700"> {med.dosage}</span>}
            {(() => {
              if (!med.variants || med.variants.length === 0) return null;
              const uniq = sortPacks([...new Set(med.variants.map(v => simplifyPack(v.pack_size)).filter(Boolean))]);
              return uniq.length === 1 ? <span className="text-slate-700">, {uniq[0]}</span> : null;
            })()}
          </h1>
          <p className="text-slate-600 mt-1.5">{formLower}</p>

          <div className="mt-5 grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
            <div className="bg-slate-50 rounded-lg p-3"><div className="text-[11px] text-slate-500 uppercase tracking-wide">Производитель</div><div className="font-medium text-slate-800">{formatManufacturer(med.manufacturer) || "—"}</div></div>
            <div className="bg-slate-50 rounded-lg p-3"><div className="text-[11px] text-slate-500 uppercase tracking-wide">Страна</div><div className="font-medium text-slate-800">{normalizeCountry(med.manufacturer_country) || '—'}</div></div>
            {med.mnn && <div className="bg-slate-50 rounded-lg p-3"><div className="text-[11px] text-slate-500 uppercase tracking-wide">МНН</div><div className="font-medium text-slate-800">{titleCase(med.mnn)}</div></div>}
          </div>

          {(() => {
            if (!med.variants || med.variants.length === 0) return null;
            const uniq = sortPacks([...new Set(med.variants.map(v => simplifyPack(v.pack_size)).filter(Boolean))]);
            if (uniq.length < 2) return null;
            return (
              <div className="mt-5" data-testid="med-pack-chips">
                <div className="text-[11px] text-slate-500 uppercase tracking-wide mb-2">Фасовка</div>
                <div className="flex flex-wrap gap-2">
                  {uniq.map((p, i) => {
                    const active = selectedPack === p || (selectedPack === null && i === 0);
                    return (
                      <button
                        key={p}
                        type="button"
                        onClick={() => setSelectedPack(p)}
                        data-testid={`pack-chip-${i}`}
                        className={
                          "px-3.5 py-1.5 rounded-full text-sm border transition " +
                          (active
                            ? "bg-emerald-600 border-emerald-600 text-white shadow-sm"
                            : "bg-white border-slate-200 text-slate-700 hover:border-emerald-300 hover:text-emerald-700")
                        }
                      >
                        {p}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })()}


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
              <h2 className="text-2xl font-bold text-slate-900">{formatName(med.name)} на карте — {city.name}</h2>
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
                <div key={pr.pharmacy_id} className={`grid grid-cols-[1fr_auto] sm:grid-cols-[1fr_130px_170px_110px_130px] items-center gap-3 px-4 py-3 hover:bg-emerald-50/30 transition ${selectedId === ph.id ? 'bg-emerald-50/50' : ''}`}>
                  <div>
                    <Link to={`/${city.id}/apteki/${ph.id}`} className="font-semibold text-slate-900 hover:text-emerald-700">{ph.name}</Link>
                    <div className="text-xs text-slate-500 mt-0.5 flex items-center gap-1.5"><MapPin className="w-3.5 h-3.5" /> {ph.address}{ph.metro && <span className="text-emerald-600"> · м. {ph.metro}</span>}</div>
                  </div>
                  <div className="hidden sm:flex items-center gap-1.5 text-xs text-slate-500 whitespace-nowrap"><Clock className="w-3.5 h-3.5 shrink-0" /> {ph.hours}</div>
                  <a href={`tel:${(ph.phone || "").replace(/[^+\d]/g, "")}`} data-testid="med-pharmacy-phone" className="hidden sm:flex items-center gap-1.5 text-sm font-medium text-slate-700 hover:text-emerald-700 whitespace-nowrap border-l border-slate-200 pl-3"><Phone className="w-4 h-4 text-emerald-600 shrink-0" /> {ph.phone}</a>
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
            <h2 className="text-2xl font-bold text-slate-900">Аналоги по МНН: {med.mnn ? titleCase(med.mnn) : '—'}</h2>
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
                <h3 className="font-semibold text-slate-900 text-sm leading-tight line-clamp-2">{formatName(a.name)}</h3>
                <p className="text-[11px] text-slate-500 mt-1 line-clamp-1">{[a.form?.toLowerCase(), a.dosage].filter(Boolean).join(', ')}</p>
                <p className="text-[11px] text-slate-400 mt-1">{formatManufacturer(a.manufacturer)}</p>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
