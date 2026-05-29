'use client';
import { formatName, formatManufacturer } from "../../../../utils/text";
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ChevronRight, ChevronLeft, MapPin, Phone, Clock, Pill, ShieldAlert, Tag, Navigation, PackageX, Maximize2, Minimize2 } from 'lucide-react';
import { useCity } from '../../../../context/CityContext';
import { Drawer as VaulDrawer } from 'vaul';
import { fetchMed, fetchAnalogs, fetchPharmacies, fetchCategories, fetchGorzdravStores, fetchGorzdravStoreDetail, fetchGorzdravStoresBulk } from '../../../../api/client';
// map: Leaflet + OSM (no API key needed)

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

// store_bitmap (base64) → Uint8Array. Бит idx взведён, если препарат есть
// в Горздрав-аптеке с этим idx. idx — стабильный индекс из gorzdrav_stores.
function decodeBitmap(b64) {
  if (!b64) return null;
  try {
    const bin = atob(b64);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return arr;
  } catch (e) { return null; }
}
function bitmapHas(mask, idx) {
  if (!mask || idx == null || idx < 0) return false;
  const byte = idx >> 3;
  return byte < mask.length && (mask[byte] & (1 << (idx & 7))) !== 0;
}

const PriceMap = React.forwardRef(function PriceMap({ med, prices, pharmacies, gorzdravStores = [], gorzdravPrice = null, gorzdravBitmap = null, cityCenter, onSelect, selected, fullscreen = false, onInteract, onViewportChange }, externalRef) {
  const ref = useRef(null);
  const mapRef = useRef(null);
  const tileLayerRef = useRef(null);
  const onInteractRef = useRef(onInteract);
  useEffect(() => { onInteractRef.current = onInteract; }, [onInteract]);
  const onViewportChangeRef = useRef(onViewportChange);
  useEffect(() => { onViewportChangeRef.current = onViewportChange; }, [onViewportChange]);

  React.useImperativeHandle(externalRef, () => ({
    centerOn: (lat, lng, zoom = 14) => {
      if (mapRef.current) {
        try { mapRef.current.setView([lat, lng], zoom, { animate: true, duration: 0.4 }); } catch (e) {}
      }
    },
  }));

  useEffect(() => {
    let cancelled = false;

    // ready() — проверка, что нужный глобал уже зарегистрирован. Без неё была
    // гонка: эффект перезапускается при подгрузке цен/остатков (deps prices.length,
    // gorzdravStores.length, …); на повторном проходе тег скрипта уже в DOM →
    // старый код резолвился сразу, и L.markerClusterGroup вызывался ДО того, как
    // плагин успел выполниться → "markerClusterGroup is not a function", 0 маркеров.
    function loadScript(src, ready) {
      return new Promise((res, rej) => {
        if (ready && ready()) { res(); return; }
        const existing = document.querySelector(`script[src="${src}"]`);
        if (existing) {
          // тег есть, но глобал ещё не готов → ждём реальной загрузки скрипта
          existing.addEventListener('load', () => res(), { once: true });
          existing.addEventListener('error', rej, { once: true });
          return;
        }
        const s = document.createElement('script'); s.src = src; s.onload = res; s.onerror = rej;
        document.head.appendChild(s);
      });
    }
    function loadCss(href) {
      if (document.querySelector(`link[href="${href}"]`)) return;
      const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = href;
      document.head.appendChild(l);
    }

    async function init() {
      loadCss('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css');
      loadCss('https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css');
      loadCss('https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css');
      await loadScript('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js', () => !!window.L);
      await loadScript('https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js', () => !!(window.L && window.L.markerClusterGroup));
      if (cancelled || !ref.current) return;

      const L = window.L;
      if (mapRef.current) { mapRef.current.remove(); mapRef.current = null; }

      const [lat, lng] = cityCenter;
      const map = L.map(ref.current, { center: [lat, lng], zoom: 11, zoomControl: true, tap: true, attributionControl: false, crs: L.CRS.EPSG3395 });
      map.invalidateSize();
      L.control.attribution({ prefix: false }).addTo(map);
      mapRef.current = map;

      const tilesKey = process.env.NEXT_PUBLIC_YANDEX_TILES_KEY;
      const tileUrl = tilesKey
        ? `https://core-renderer-tiles.maps.yandex.net/tiles?l=map&x={x}&y={y}&z={z}&lang=ru_RU&apikey=${tilesKey}`
        : 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
      const attribution = tilesKey
        ? '© <a href="https://yandex.ru/maps">Яндекс Карты</a>'
        : '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';
      const tileLayer = L.tileLayer(tileUrl, { attribution, maxZoom: 19, subdomains: tilesKey ? [] : ['a','b','c'] }).addTo(map);
      tileLayerRef.current = tileLayer;

      const fireInteract = () => { if (onInteractRef.current) onInteractRef.current(); };
      ref.current.addEventListener('pointerdown', fireInteract, { passive: true });
      ref.current.addEventListener('wheel', fireInteract, { passive: true });

      function pillIcon(price) {
        // .ymap-price-pill уже сам себя позиционирует через CSS
        // `transform: translate(-50%, -100%)` (низ-центр пилюли совпадает с
        // верхним-левым углом контейнера), а ::after-хвост висит на 7 px
        // ниже пилюли. Чтобы кончик хвоста попал на lat/lng, контейнер
        // должен стоять на 7 px ВЫШЕ точки — то есть anchor = [0, 7]
        // (lat/lng внутри иконки на 7 px ниже её top-left). Иначе iconAnchor
        // даёт второй сдвиг поверх CSS-трансформа и маркер уезжает в сторону
        // (на zoom 11 это ~1.7 км — видно сразу, на zoom 18 ~30 м — почти ОК).
        return L.divIcon({
          className: '',
          html: `<div class="ymap-price-pill">${price} ₽</div>`,
          iconAnchor: [0, 7],
          iconSize: [80, 36],
        });
      }

      const cluster = L.markerClusterGroup({
        maxClusterRadius: 80,
        spiderfyOnMaxZoom: false,
        showCoverageOnHover: false,
        zoomToBoundsOnClick: true,
        removeOutsideVisibleBounds: true,
        animate: true,
        iconCreateFunction(c) {
          return L.divIcon({
            className: '',
            html: `<div class="ymap-cluster">${c.getChildCount()}</div>`,
            iconAnchor: [20, 20],
            iconSize: [40, 40],
          });
        },
      });

      // HTML-экранирование (popupContent рендерится как HTML).
      const esc = (str) => String(str ?? '').replace(/[&<>"']/g, ch => (
        { '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[ch]
      ));
      // Парсим hours по запятой/точке-с-запятой — каждый кусок на свою строку.
      // 'ПН-ПТ с 08:00 до 22:00, СБ-ВС с 09:00 до 22:00' -> 2 строки.
      const splitHours = (h) => {
        if (!h) return [];
        return String(h).split(/[,;·]\s*/).map(s => s.trim()).filter(Boolean);
      };
      const popupContent = ({ title, address, hours, phone, price, lat, lng }) => {
        const phoneClean = (phone || '').replace(/[^+\d]/g, '');
        const hoursLines = splitHours(hours);
        // Координаты для deep-link'ов.
        // Я.Карты: rtext=~LAT,LNG;  2GIS: routeSearch/.../to/LNG,LAT (порядок обратный).
        const yandexApp = `yandexmaps://build_route_on_map?lat_to=${lat}&lon_to=${lng}`;
        const yandexWeb = `https://yandex.ru/maps/?rtext=~${lat}%2C${lng}&rtt=auto&z=15`;
        const dgisApp   = `dgis://2gis.ru/routeSearch/rsType/car/to/${lng},${lat}`;
        const dgisWeb   = `https://2gis.ru/routeSearch/rsType/car/to/${lng},${lat}/go`;
        return [
          '<div class="ymap-popup">',
          `<div class="ymap-popup__title">${esc(title)}</div>`,
          address ? `<div class="ymap-popup__row">📍 <span>${esc(address)}</span></div>` : '',
          hoursLines.length ? `<div class="ymap-popup__row">🕒 <span>${hoursLines.map(esc).join('<br>')}</span></div>` : '',
          phone   ? `<div class="ymap-popup__row">📞 <a href="tel:${esc(phoneClean)}">${esc(phone)}</a></div>` : '',
          price != null ? `<div class="ymap-popup__price">${esc(price)} ₽</div>` : '',
          '<div class="ymap-popup__routes">',
            `<button type="button" class="ymap-popup__route ymap-popup__route--ya" data-app="${esc(yandexApp)}" data-web="${esc(yandexWeb)}">Я.Карты</button>`,
            `<button type="button" class="ymap-popup__route ymap-popup__route--dgis" data-app="${esc(dgisApp)}" data-web="${esc(dgisWeb)}">2GIS</button>`,
          '</div>',
          '</div>',
        ].join('');
      };

      const partnerBounds = [];
      prices.forEach(pr => {
        const ph = pharmacies.find(p => p.id === pr.pharmacy_id);
        if (!ph || !ph.lat || !ph.lng || ph.id === 'gorzdrav') return;
        const m = L.marker([ph.lat, ph.lng], { icon: pillIcon(pr.price) });
        m.bindPopup(popupContent({
          title: ph.name,
          address: ph.address,
          hours: ph.hours,
          phone: ph.phone,
          price: pr.price,
          lat: ph.lat,
          lng: ph.lng,
        }), { maxWidth: 280, autoPan: true });
        m.on('click', () => { onSelect && onSelect(ph.id); });
        cluster.addLayer(m);
        partnerBounds.push([ph.lat, ph.lng]);
      });

      if (gorzdravPrice !== null && gorzdravStores.length > 0) {
        // Маркер только для аптек, где препарат реально есть (store_bitmap),
        // а не для всех ~1900 точек сети.
        const gzMask = decodeBitmap(gorzdravBitmap);
        gorzdravStores.forEach(store => {
          if (!store.lat || !store.lng) return;
          if (!bitmapHas(gzMask, store.idx)) return;
          const m = L.marker([store.lat, store.lng], { icon: pillIcon(gorzdravPrice) });
          // Лёгкий placeholder-popup (название + цена + кнопки маршрута).
          // Адрес, часы, телефон — догружаются по клику и подменяют popup.
          m.bindPopup(popupContent({
            title: 'Горздрав',
            address: null,
            hours: null,
            phone: null,
            price: gorzdravPrice,
            lat: store.lat,
            lng: store.lng,
          }), { maxWidth: 280, autoPan: true });
          m.on('click', () => {
            onSelect && onSelect('gorzdrav_' + store.store_id);
            // Lazy-load полной инфы про эту аптеку и подменяем содержимое popup'а.
            fetchGorzdravStoreDetail(store.store_id).then(full => {
              const popup = m.getPopup();
              if (!popup) return;
              popup.setContent(popupContent({
                title: full.full_name || 'Горздрав',
                address: full.address,
                hours: full.is_24h ? 'Круглосуточно' : full.hours,
                phone: full.phone,
                price: gorzdravPrice,
                lat: full.lat || store.lat,
                lng: full.lng || store.lng,
              }));
            }).catch(() => {});
          });
          cluster.addLayer(m);
        });
      }

      map.invalidateSize();
      map.setView([lat, lng], 11, { animate: false });
      map.addLayer(cluster);

      // Динамический список "видно на карте": при каждом moveend (debounce 300мс)
      // даём родителю текущий центр и bounds. Родитель сам пересчитывает,
      // какие 15 аптек попадают в viewport и сортирует.
      let viewportTimer = null;
      const fireViewport = () => {
        if (!onViewportChangeRef.current) return;
        const c = map.getCenter();
        const b = map.getBounds();
        onViewportChangeRef.current({
          center: { lat: c.lat, lng: c.lng },
          bounds: { south: b.getSouth(), north: b.getNorth(), west: b.getWest(), east: b.getEast() },
        });
      };
      const onMoveEnd = () => {
        clearTimeout(viewportTimer);
        viewportTimer = setTimeout(fireViewport, 300);
      };
      map.on('moveend zoomend', onMoveEnd);
      // Первый раз — сразу
      fireViewport();

      // Делегированный клик на кнопки маршрута. Стратегия:
      //   1. window.location.href = app-scheme — iOS покажет диалог
      //      "Открыть в Яндекс.Карты?". Если юзер согласится — приложение
      //      откроется и страница уйдёт в background (visibilitychange).
      //   2. Слушаем visibilitychange. Если за 2.5с страница ушла в bg —
      //      приложение открылось, ничего не делаем.
      //   3. Если visibility НЕ сменился — приложение не установлено,
      //      открываем веб как fallback.
      const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
      const onPopupClick = (e) => {
        const btn = e.target.closest && e.target.closest('.ymap-popup__route');
        if (!btn) return;
        e.preventDefault();
        const app = btn.getAttribute('data-app');
        const web = btn.getAttribute('data-web');
        if (!app || !web) return;
        // На десктопе приложение никогда не установлено — сразу веб, без ожидания.
        if (!isMobile) {
          window.open(web, '_blank', 'noopener,noreferrer');
          return;
        }
        // Мобильная схема: app-scheme → fallback на веб, если visibility не сменился.
        let appOpened = false;
        const onVis = () => { if (document.hidden) appOpened = true; };
        document.addEventListener('visibilitychange', onVis);
        window.location.href = app;
        setTimeout(() => {
          document.removeEventListener('visibilitychange', onVis);
          if (!appOpened) {
            window.open(web, '_blank', 'noopener,noreferrer');
          }
        }, 2500);
      };
      ref.current.addEventListener('click', onPopupClick);

      // userMoved отслеживаем ТОЛЬКО по реальному pointerdown (не по leaflet-событиям,
      // т.к. setView сам триггерит zoomstart и блокировал retry).
      let userMoved = false;
      const markMoved = () => { userMoved = true; };
      ref.current.addEventListener('pointerdown', markMoved, { passive: true });
      ref.current.addEventListener('wheel', markMoved, { passive: true });
      [60, 250, 700].forEach(ms => {
        setTimeout(() => {
          if (cancelled || !mapRef.current || userMoved) return;
          mapRef.current.invalidateSize();
          mapRef.current.setView([lat, lng], 11, { animate: false });
        }, ms);
      });
    }

    init().catch(e => console.error('Map init error', e));
    return () => {
      cancelled = true;
      if (mapRef.current) { mapRef.current.remove(); mapRef.current = null; }
    };
    // eslint-disable-next-line
  }, [med?.slug, cityCenter[0], cityCenter[1], prices.length, gorzdravStores.length, gorzdravPrice, gorzdravBitmap, fullscreen]);

  useEffect(() => {
    if (!mapRef.current) return;
    // При смене fullscreen контейнер ресайзится. Leaflet нужно явно сказать:
    //   1) invalidateSize — пересчитать пиксельный размер карты
    //   2) tileLayer.redraw — принудительно перезапросить тайлы под новый
    //      viewport (без этого пустые тайлы остаются белыми)
    const map = mapRef.current;
    const refresh = () => {
      try {
        map.invalidateSize({ animate: false });
        if (tileLayerRef.current) tileLayerRef.current.redraw();
      } catch (e) {}
    };
    refresh();
    const ids = [50, 200, 500].map(ms => setTimeout(refresh, ms));
    return () => ids.forEach(clearTimeout);
  }, [fullscreen]);

  return <div ref={ref} className={fullscreen ? "w-full h-full relative isolate" : "w-full h-[360px] md:h-[460px] rounded-xl overflow-hidden border border-slate-100 relative isolate"} />;
});


// Карточка в списке "Видно на карте" — общая для bottom-sheet и блока под картой.
function ViewportListItem({ item, onClick, selected = false }) {
  const ya = `https://yandex.ru/maps/?rtext=~${item.lat}%2C${item.lng}&rtt=auto&z=15`;
  const dgis = `https://2gis.ru/routeSearch/rsType/car/to/${item.lng},${item.lat}/go`;
  const hoursLines = item.hours ? String(item.hours).split(/[,;·]\s*/).map(s => s.trim()).filter(Boolean) : [];
  const phoneClean = (item.phone || '').replace(/[^+\d]/g, '');
  return (
    <div
      className={`px-4 py-3 active:bg-slate-50 transition ${selected ? 'bg-emerald-50/60' : ''}`}
      data-testid="viewport-list-item"
    >
      <button type="button" onClick={onClick} className="w-full text-left flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-slate-900 text-sm leading-tight">{item.name || (item.source === 'gorzdrav' ? 'Горздрав' : 'Аптека')}</div>
          {item.address && (
            <div className="text-[11px] text-slate-500 mt-0.5 flex items-start gap-1">
              <MapPin className="w-3 h-3 shrink-0 mt-0.5" />
              <span>{item.address}</span>
            </div>
          )}
          {hoursLines.length > 0 && (
            <div className="text-[11px] text-slate-500 mt-0.5 flex items-start gap-1">
              <Clock className="w-3 h-3 shrink-0 mt-0.5" />
              <span>{hoursLines.map((h,i) => <React.Fragment key={i}>{i>0 && <br/>}{h}</React.Fragment>)}</span>
            </div>
          )}
          {item.phone && (
            <div className="text-[11px] mt-0.5 flex items-center gap-1">
              <Phone className="w-3 h-3 shrink-0 text-emerald-700" />
              <a href={`tel:${phoneClean}`} onClick={(e) => e.stopPropagation()} className="text-emerald-700 font-medium">{item.phone}</a>
            </div>
          )}
        </div>
        <div className="text-right shrink-0">
          <div className="text-base font-bold text-emerald-700 leading-tight">{item.price} ₽</div>
        </div>
      </button>
      <div className="mt-2 flex items-center gap-2">
        <a
          href={ya}
          target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center justify-center gap-1 text-[11px] font-semibold px-3 py-1.5 rounded-md border border-yellow-300 text-yellow-800 active:bg-yellow-50"
        >Я.Карты</a>
        <a
          href={dgis}
          target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center justify-center gap-1 text-[11px] font-semibold px-3 py-1.5 rounded-md border border-emerald-300 text-emerald-800 active:bg-emerald-50"
        >2GIS</a>
      </div>
    </div>
  );
}

export default function MedDetail({ initialMed = null }) {
  const { slug, city: cityParam } = useParams();
  const { city, cities, setCity } = useCity();
  const [selectedId, setSelectedId] = useState(null);
  const [mapFullscreen, setMapFullscreen] = useState(false);
  const priceMapRef = useRef(null);
  const SNAP_POINTS = [0.25, 0.55, 0.9];
  const [snapPoint, setSnapPoint] = useState(0.55);

  // Lock body scroll + ESC to close when map is fullscreen.
  useEffect(() => {
    if (!mapFullscreen) {
      setSnapPoint(0.55); // reset for next open
      return;
    }
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (e) => { if (e.key === 'Escape') setMapFullscreen(false); };
    window.addEventListener('keydown', onKey);
    return () => { document.body.style.overflow = prev; window.removeEventListener('keydown', onKey); };
  }, [mapFullscreen]);
  const [med, setMed] = useState(initialMed);
  const [analogs, setAnalogs] = useState([]);
  const [pharmacies, setPharmacies] = useState([]);
  const [gorzdravStores, setGorzdravStores] = useState([]);
  // Флаг «список Горздрав-аптек уже загружен» (вне зависимости от того,
  // получили ли что-то). Нужен, чтобы отличать "ещё грузим" от "загрузили,
  // в видимой области карты ничего нет" — раньше показывался бесконечный
  // «Загрузка списка аптек…».
  const [gorzdravStoresLoaded, setGorzdravStoresLoaded] = useState(false);
  // Динамический список аптек, видимых на карте + 15 ближайших к центру.
  // Обновляется при каждом moveend/zoomend (debounce внутри PriceMap).
  const [viewportList, setViewportList] = useState([]);
  const [viewportVisible, setViewportVisible] = useState(15);
  const lastViewportRef = useRef(null);
  const [loading, setLoading] = useState(!initialMed);
  const [selectedPack, setSelectedPack] = useState(null);
  const [notFound, setNotFound] = useState(false);
  const [categories, setCategories] = useState([]);
  useEffect(() => { fetchCategories().then(setCategories).catch(() => {}); }, []);

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
    // Если нет initialMed (SPA-навигация между препаратами) — показываем спиннер.
    // При первом маунте с SSR-данными loading уже false, не перезатираем.
    if (!med) setLoading(true);
    setNotFound(false);
    setGorzdravStoresLoaded(false);
    // Горздрав-аптек 1937 штук — грузим параллельно, но НЕ блокируем рендер.
    // Карта появится сразу же с партнёрскими маркерами, кружки Горздрав
    // дорисуются как только данные приедут (~100-300мс).
    fetchGorzdravStores(city.id)
      .then(gz => { if (!cancelled) setGorzdravStores(gz); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setGorzdravStoresLoaded(true); });
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

  // Упаковки, для которых у Горздрав есть реальные данные — приоритет дефолта.
  const inStockPacks = useMemo(() => {
    const arr = (med?.prices_by_city?.[city.id] || [])
      .filter(p => p.pharmacy_id === 'gorzdrav')
      .map(p => p.gz_pack)
      .filter(Boolean);
    return new Set(arr);
  }, [med, city.id]);

  // Default = первая упаковка с реальными ценами Горздрав, иначе packs[0].
  // Это нужно, чтобы при открытии страницы пользователь сразу видел данные,
  // а не пустую "нет в наличии" фасовку.
  const defaultPack = useMemo(() => {
    if (!packs.length) return null;
    if (inStockPacks.size === 0) return packs[0];
    return packs.find(p => inStockPacks.has(p)) || packs[0];
  }, [packs, inStockPacks]);

  // Active pack = explicit selection || smart default || null.
  const activePack = selectedPack || defaultPack;

  // Parse leading number from pack label ('30 шт' → 30, '50 г' → 50, '1.5 мл' → 1.5).
  function packQty(p) {
    if (!p) return null;
    const m = String(p).match(/^(\d+(?:\.\d+)?)/);
    return m ? parseFloat(m[1]) : null;
  }

  // Нормализация упаковки для сравнения с Горздрав: "N × M unit" → "N*M unit".
  // В med.variants упаковки хранятся как "2 × 10 шт", а Горздрав отдаёт уже
  // перемноженное "20 шт". Без нормализации матчинг по строкам теряет
  // активную упаковку, и весь Горздрав-блок (карта, маркеры, цены) исчезает.
  function packTotal(p) {
    if (!p) return '';
    const s = String(p).trim();
    const m = s.match(/^(\d+(?:[.,]\d+)?)\s*[×xх]\s*(\d+(?:[.,]\d+)?)\s*(.*)$/i);
    if (m) {
      const n = parseFloat(m[1].replace(',', '.'));
      const k = parseFloat(m[2].replace(',', '.'));
      const unit = (m[3] || '').trim();
      return `${Math.round(n * k)}${unit ? ' ' + unit : ''}`;
    }
    return s;
  }

  // Deterministic 32-bit hash of a string.
  function hashStr(s) {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    return Math.abs(h);
  }

  const prices = useMemo(() => {
    if (!med) return [];
    const all = [...((med.prices_by_city || {})[city.id] || [])];
    // Извлекаем фасовку из имени Горздрав ("... 28 шт" / "... 50 мл")
    // и сравниваем с активной фасовкой. Горздрав хранит каждую упаковку
    // как отдельную позицию, и у нас в БД маппится только ОДНА из них на slug,
    // поэтому при переключении фасовки нужно скрывать запись, если она
    // относится к другой упаковке.
    const extractGzPack = (name) => {
      if (!name) return null;
      const m = String(name).match(/(\d+(?:[\.,]\d+)?)\s*(шт|мл|мг|мкг|г|л)[^\d]*$/i);
      if (!m) return null;
      const qty = m[1].replace(',', '.');
      return qty + ' ' + m[2].toLowerCase();
    };
    const gorzdravAll = all.filter(p => p.pharmacy_id === 'gorzdrav');
    const activeTotal = packTotal(activePack);
    const gorzdrav = packs.length >= 2 && activePack
      ? gorzdravAll.filter(p => {
          const gzPack = p.gz_pack || extractGzPack(p.gz_name);
          if (!gzPack) return true;
          return packTotal(gzPack) === activeTotal;
        })
      : gorzdravAll;
    const list = all.filter(p => p.pharmacy_id !== 'gorzdrav');

    let result;
    if (packs.length >= 2 && activePack && list.length > 0) {
      const baseQty = packQty(packs[0]) || 1;
      const activeQty = packQty(activePack) || baseQty;
      const ratio = activeQty / baseQty;
      const packSeed = hashStr(med.slug + '|' + activePack);
      const priceFactor = Math.pow(ratio, 0.78);
      const packIdx = packs.indexOf(activePack);
      const ofMax = packs.length - 1 || 1;
      const stockCount = Math.max(3, Math.round(12 - (packIdx / ofMax) * 6));

      const scaled = list.map((p, i) => {
        const j = ((packSeed + i * 2654435761) >>> 0) % 1000;
        const jitter = 0.92 + (j / 1000) * 0.16;
        const newPrice = Math.max(5, Math.round((p.price * priceFactor * jitter) / 5) * 5);
        const newQty = ((packSeed >>> 1) + i * 16807) % 30 + 1;
        return { ...p, price: newPrice, qty: newQty };
      });

      result = scaled
        .map((p, i) => ({ p, h: ((packSeed ^ hashStr(p.pharmacy_id)) >>> 0) }))
        .sort((a, b) => a.h - b.h)
        .slice(0, stockCount)
        .map(x => x.p);
    } else {
      result = list;
    }

    return [...result, ...gorzdrav].sort((a, b) => a.price - b.price);
  }, [med, city.id, packs, activePack]);

  // Гаверсин-расстояние в км между двумя точками.
  const haversine = (lat1, lng1, lat2, lng2) => {
    const R = 6371;
    const toRad = (d) => (d * Math.PI) / 180;
    const dLat = toRad(lat2 - lat1);
    const dLng = toRad(lng2 - lng1);
    const a = Math.sin(dLat/2)**2 + Math.cos(toRad(lat1))*Math.cos(toRad(lat2))*Math.sin(dLng/2)**2;
    return 2 * R * Math.asin(Math.sqrt(a));
  };

  // Обработчик изменения viewport — вычисляет 15 ближайших аптек в bbox,
  // сортирует по цене (asc), при равной цене — по расстоянию (asc).
  // Рефы на актуальные данные — чтобы коллбэк не пересоздавался и не рвал
  // подписку у PriceMap, но всегда читал свежие prices/pharmacies/stores.
  const dataRef = useRef({ prices, pharmacies, gorzdravStores });
  useEffect(() => { dataRef.current = { prices, pharmacies, gorzdravStores }; }, [prices, pharmacies, gorzdravStores]);

  const onMapViewportChange = useCallback(async ({ center, bounds }) => {
    lastViewportRef.current = { center, bounds };
    const { prices, pharmacies, gorzdravStores } = dataRef.current;
    const gzPrice = prices.find(p => p.pharmacy_id === 'gorzdrav')?.price ?? null;

    // 1. Партнёрские аптеки в bbox + у них есть цена для активной упаковки.
    const partnerEntries = prices
      .map(pr => {
        if (pr.pharmacy_id === 'gorzdrav') return null;
        const ph = pharmacies.find(p => p.id === pr.pharmacy_id);
        if (!ph || !ph.lat || !ph.lng) return null;
        if (ph.lat < bounds.south || ph.lat > bounds.north) return null;
        if (ph.lng < bounds.west  || ph.lng > bounds.east)  return null;
        return {
          key: 'partner_' + ph.id,
          source: 'partner',
          ph_id: ph.id,
          name: ph.name,
          address: ph.address,
          hours: ph.hours,
          phone: ph.phone,
          lat: ph.lat,
          lng: ph.lng,
          price: pr.price,
          distance: haversine(center.lat, center.lng, ph.lat, ph.lng),
        };
      })
      .filter(Boolean);

    // 2. Горздрав-аптеки в bbox, где препарат реально есть (store_bitmap).
    const gzMask = decodeBitmap(prices.find(p => p.pharmacy_id === 'gorzdrav')?.store_bitmap);
    const gzCandidates = gzPrice !== null
      ? gorzdravStores
          .filter(s => bitmapHas(gzMask, s.idx) && s.lat >= bounds.south && s.lat <= bounds.north && s.lng >= bounds.west && s.lng <= bounds.east)
          .map(s => ({
            key: 'gorzdrav_' + s.store_id,
            source: 'gorzdrav',
            store_id: s.store_id,
            lat: s.lat,
            lng: s.lng,
            price: gzPrice,
            distance: haversine(center.lat, center.lng, s.lat, s.lng),
          }))
      : [];

    // 3. Объединяем и сортируем (price asc, distance asc) — БЕЗ лимита.
    //    Показываем все аптеки в зоне карты; детали Горздрав-аптек
    //    догружаются лениво только для видимых карточек (эффект ниже).
    const combined = [...partnerEntries, ...gzCandidates]
      .sort((a, b) => a.price - b.price || a.distance - b.distance);

    setViewportList(combined);
    setViewportVisible(15);   // движение карты — снова показываем первые 15
  }, []);

  // Когда данные обновляются (gorzdravStores догрузились / поменялся pack / город) —
  // пересчитываем список под текущий viewport.
  useEffect(() => {
    if (lastViewportRef.current) onMapViewportChange(lastViewportRef.current);
  }, [prices, pharmacies, gorzdravStores, onMapViewportChange]);

  // Ленивая догрузка деталей Горздрав-аптек — только для видимых карточек.
  useEffect(() => {
    const need = viewportList
      .slice(0, viewportVisible)
      .filter(x => x.source === 'gorzdrav' && !x.name)
      .map(x => x.store_id);
    if (need.length === 0) return;
    let cancelled = false;
    fetchGorzdravStoresBulk(need).then(details => {
      if (cancelled) return;
      const byId = Object.fromEntries(details.map(d => [d.store_id, d]));
      setViewportList(prev => prev.map(item => {
        if (item.source === 'gorzdrav' && !item.name && byId[item.store_id]) {
          const d = byId[item.store_id];
          return {
            ...item,
            name: d.full_name || 'Горздрав',
            address: d.address,
            hours: d.is_24h ? 'Круглосуточно' : d.hours,
            phone: d.phone,
          };
        }
        return item;
      }));
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [viewportList, viewportVisible]);


  if (loading) {
    // Высота = viewport: пока React гидрирует и /api/medications не пришёл,
    // главный контейнер должен занимать весь экран, иначе футер залезает в
    // visible area и при появлении контента улетает вниз на ~2400px —
    // даёт катастрофический CLS (0.39 в Lighthouse mobile).
    return (
      <div className="max-w-7xl mx-auto px-4 py-16 text-center text-slate-500 min-h-[100dvh]">
        Загрузка препарата…
      </div>
    );
  }

  if (notFound || !med) return (
    <div className="max-w-7xl mx-auto px-4 py-16 text-center">
      <h1 className="text-2xl font-bold mb-2">Препарат не найден</h1>
      <Link href={`/${city.id}/preparaty`} className="text-emerald-700 hover:underline">К каталогу</Link>
    </div>
  );

  // noAvailability: считаем по СЫРЫМ данным prices_by_city (по всем упаковкам),
  // не по фильтрованному prices. Используется, чтобы решить, показывать ли блок
  // аналогов на мобильной версии (показываем только если препарата вообще нет).
  const noAvailability = !((med?.prices_by_city?.[city.id] || []).length);

  const minPrice = prices.length ? Math.min(...prices.map(p => p.price)) : null;
  const maxPrice = prices.length ? Math.max(...prices.map(p => p.price)) : null;
  // For Gorzdrav entries qty = number of stores; for partner pharmacies count = 1 each.
  const totalPharmacyCount = prices.reduce((sum, p) => {
    return sum + (p.pharmacy_id === 'gorzdrav' ? (p.qty || 0) : 1);
  }, 0);
  
  const formLower = (med.form || '').toLowerCase();

  // (Schema.org Drug рендерится в SSR-обёртке page.jsx через medGraphJsonLd.)

  return (
    <div className="max-w-7xl mx-auto px-4 py-5 md:py-8" data-testid="med-detail-page">
      

      <nav className="text-xs text-slate-500 mb-4 flex items-center flex-wrap gap-x-1.5">
        <Link href={`/${city.id}`} className="hover:text-emerald-700">Главная</Link>
        <ChevronRight className="w-3 h-3" />
        <Link href={`/${city.id}/preparaty`} className="hover:text-emerald-700">Каталог</Link>
        {med.category && med.category !== 'other' && (
          <>
            <ChevronRight className="w-3 h-3" />
            <Link href={`/${city.id}/kategorii/${med.category}`} className="hover:text-emerald-700">{(categories.find(c => c.slug === med.category) || {}).title || med.category.replace(/-/g, ' ')}</Link>
          </>
        )}
        <ChevronRight className="w-3 h-3" /><span className="text-slate-700">{formatName(med.name)}</span>
      </nav>

      <div className="grid lg:grid-cols-[380px_1fr] gap-6 md:gap-8 mb-8 md:mb-10">
        <div className="bg-white border border-slate-100 rounded-2xl p-3 md:p-6">
          <div className="aspect-square mx-auto md:mx-0 max-w-[240px] md:max-w-none rounded-xl bg-slate-50 overflow-hidden flex items-center justify-center">
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
          <h1 className="text-2xl sm:text-3xl md:text-4xl font-bold text-slate-900 leading-tight" data-testid="med-h1">
            {formatName(med.name)}
            {(() => {
              if (!med.variants || med.variants.length === 0) return null;
              const uniq = sortPacks([...new Set(med.variants.map(v => simplifyPack(v.pack_size)).filter(Boolean))]);
              return uniq.length === 1 ? <span className="text-slate-700">, {uniq[0]}</span> : null;
            })()}
          </h1>
          {med.dosage && <p className="text-slate-700 font-medium mt-1">{med.dosage}</p>}
          <p className="text-slate-600 mt-0.5">{formLower}</p>

          <div className="mt-5 grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
            <div className="bg-slate-50 rounded-lg p-3 min-w-0"><div className="text-[11px] text-slate-500 uppercase tracking-wide">Производитель</div><div className="font-medium text-slate-800 break-words">{formatManufacturer(med.manufacturer) || "—"}</div></div>
            <div className="bg-slate-50 rounded-lg p-3 min-w-0"><div className="text-[11px] text-slate-500 uppercase tracking-wide">Страна</div><div className="font-medium text-slate-800 break-words">{normalizeCountry(med.manufacturer_country) || '—'}</div></div>
            {med.mnn && <div className="bg-slate-50 rounded-lg p-3 min-w-0 col-span-2 sm:col-span-1"><div className="text-[11px] text-slate-500 uppercase tracking-wide">МНН</div><div className="font-medium text-slate-800 break-words">{titleCase(med.mnn)}</div></div>}
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
                    const active = p === activePack;
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
              <div className="text-xs text-emerald-800/80">Минимальная цена в {city.inLoc}</div>
              <div className="text-3xl font-extrabold text-emerald-700 whitespace-nowrap">
                {minPrice}&nbsp;₽
              </div>
              <div className="text-sm text-slate-600 mt-1">
                {minPrice !== maxPrice ? (
                  <>от&nbsp;{minPrice}&nbsp;₽ до&nbsp;{maxPrice}&nbsp;₽ · в&nbsp;{totalPharmacyCount}&nbsp;аптеках</>
                ) : (
                  <>в&nbsp;{totalPharmacyCount}&nbsp;аптеках</>
                )}
              </div>
            </div>
          )}

          {prices.length === 0 && (
            <div className="mt-5 bg-amber-50/50 border border-amber-200 rounded-xl p-4" data-testid="out-of-stock-section">
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-full bg-amber-50 border border-amber-200 flex items-center justify-center shrink-0">
                  <PackageX className="w-5 h-5 text-amber-600" />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="text-base font-semibold text-slate-900 leading-snug">
                    Препарата сейчас нет в наших аптеках-партнёрах
                  </h2>
                  <p className="text-sm text-slate-600 leading-snug mt-1">
                    Временно отсутствует во всех аптеках-партнёрах.
                    {med.mnn ? <> Попробуйте аналог с тем же действующим веществом — <b>{titleCase(med.mnn)}</b>.</> : <> Попробуйте поискать аналог в той же категории.</>}
                  </p>
                  {analogs.length > 0 && (
                    <button
                      data-testid="show-analogs-btn"
                      onClick={() => {
                        const el = document.querySelector('[data-testid="analogs-section"]');
                        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
                      }}
                      className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-emerald-700 hover:text-emerald-800"
                    >
                      Показать аналоги <ChevronRight className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Map */}
      {prices.length > 0 && (
        <section
          className={mapFullscreen ? "fixed inset-0 z-[70] bg-white flex flex-col" : "mb-8 md:mb-10"}
          data-testid="med-map-section"
        >
          {!mapFullscreen && (
            <div className="flex items-end justify-between mb-3 gap-3">
              <div className="min-w-0">
                <h2 className="text-xl md:text-2xl font-bold text-slate-900 leading-tight">{formatName(med.name)} на карте — {city.name}</h2>
                <p className="text-xs md:text-sm text-slate-500 mt-1">Нажмите на облачко с ценой, чтобы увидеть адрес и наличие</p>
              </div>
              <button
                type="button"
                onClick={() => setMapFullscreen(true)}
                data-testid="map-fullscreen-open"
                className="md:hidden shrink-0 inline-flex items-center justify-center w-11 h-11 rounded-xl border border-slate-200 bg-white text-slate-700 active:bg-slate-50 transition"
                aria-label="Развернуть карту"
              >
                <Maximize2 className="w-5 h-5" />
              </button>
            </div>
          )}

          {/* Fullscreen top bar (mobile) — overlay on top of map */}
          {mapFullscreen && (
            <div
              className="absolute top-0 inset-x-0 z-[5] flex items-center gap-2 px-3 py-2.5 border-b border-slate-100 bg-white/95 backdrop-blur"
              style={{ paddingTop: 'calc(env(safe-area-inset-top) + 10px)' }}
            >
              <button
                type="button"
                onClick={() => setMapFullscreen(false)}
                data-testid="map-fullscreen-close"
                className="inline-flex items-center justify-center w-10 h-10 rounded-xl text-slate-700 active:bg-slate-100"
                aria-label="Свернуть карту"
              >
                <ChevronLeft className="w-6 h-6" />
              </button>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-slate-900 truncate">{formatName(med.name)}</div>
                <div className="text-[11px] text-slate-500">от {Math.min(...prices.map(p => p.price))} ₽ · {prices.length} {prices.length === 1 ? 'аптека' : (prices.length < 5 ? 'аптеки' : 'аптек')}</div>
              </div>
              <button
                type="button"
                onClick={() => setMapFullscreen(false)}
                data-testid="map-fullscreen-minimize"
                className="inline-flex items-center justify-center w-10 h-10 rounded-xl text-slate-500 active:bg-slate-100"
                aria-label="Закрыть"
              >
                <Minimize2 className="w-5 h-5" />
              </button>
            </div>
          )}

          {/* Map: fills the entire fullscreen section (sheet overlays on top) */}
          <div className={mapFullscreen ? "absolute inset-0" : ""}>
            <PriceMap
              ref={priceMapRef}
              med={med}
              prices={prices}
              pharmacies={pharmacies}
              gorzdravStores={gorzdravStores}
              gorzdravPrice={prices.find(p => p.pharmacy_id === 'gorzdrav')?.price ?? null}
              gorzdravBitmap={prices.find(p => p.pharmacy_id === 'gorzdrav')?.store_bitmap ?? null}
              cityCenter={city.center}
              onSelect={(pid) => {
                setSelectedId(pid);
                if (mapFullscreen) {
                  setSnapPoint(0.25);
                  const sp = pharmacies.find(p => p.id === pid);
                  if (sp) setTimeout(() => priceMapRef.current?.centerOn(sp.lat, sp.lng, 15), 300);
                }
              }}
              selected={selectedId}
              fullscreen={mapFullscreen}
              onInteract={() => setSnapPoint(0.25)}
              onViewportChange={onMapViewportChange}
            />
          </div>

          {/* Bottom sheet with drag-handle and snap-points (vaul) */}
          {mapFullscreen && (
            <VaulDrawer.Root
              open
              modal={false}
              dismissible={false}
              snapPoints={SNAP_POINTS}
              activeSnapPoint={snapPoint}
              setActiveSnapPoint={setSnapPoint}
            >
              <VaulDrawer.Portal>
                <VaulDrawer.Content
                  data-testid="map-pharmacy-sheet"
                  className="fixed inset-x-0 bottom-0 z-[80] flex flex-col rounded-t-2xl border-t border-slate-200 bg-white shadow-2xl outline-none h-full max-h-[97dvh]"
                  aria-describedby={undefined}
                >
                  <VaulDrawer.Title className="sr-only">Аптеки рядом</VaulDrawer.Title>
                  {/* Drag handle (visual + tap-zone) */}
                  <div className="shrink-0 pt-2.5 pb-2 flex justify-center cursor-grab active:cursor-grabbing touch-none" data-testid="map-sheet-drag-handle">
                    <div className="w-12 h-1.5 rounded-full bg-slate-400" style={{ minHeight: '6px' }} />
                  </div>
                  <div className="shrink-0 border-b border-slate-100 px-4 py-2 flex items-center justify-between">
                    <div className="text-sm font-semibold text-slate-900">Видно на карте ({viewportList.length})</div>
                    <div className="text-xs text-slate-500">Сначала дешевле</div>
                  </div>
                  <div
                    data-vaul-no-drag
                    className="flex-1 overflow-y-auto divide-y divide-slate-100 overscroll-contain"
                    style={{ paddingBottom: 'calc(env(safe-area-inset-bottom) + 80px)', WebkitOverflowScrolling: 'touch' }}
                  >
                    {viewportList.slice(0, viewportVisible).map(item => (
                      <ViewportListItem
                        key={item.key}
                        item={item}
                        onClick={() => {
                          setSelectedId(item.key);
                          setSnapPoint(0.25);
                          setTimeout(() => priceMapRef.current?.centerOn(item.lat, item.lng, 15), 300);
                        }}
                        selected={selectedId === item.key}
                      />
                    ))}
                    {viewportVisible < viewportList.length && (
                      <div className="p-3">
                        <button
                          type="button"
                          onClick={() => setViewportVisible(v => v + 15)}
                          className="w-full py-2.5 rounded-lg border border-emerald-300 text-emerald-700 text-sm font-semibold active:bg-emerald-50"
                        >
                          Показать ещё ({viewportList.length - viewportVisible})
                        </button>
                        <p className="text-[11px] text-slate-400 text-center mt-2">
                          Приблизьте карту, чтобы сузить список аптек
                        </p>
                      </div>
                    )}
                  </div>
                </VaulDrawer.Content>
              </VaulDrawer.Portal>
            </VaulDrawer.Root>
          )}
        </section>
      )}

      {/* Аптеки, видимые на карте — динамически обновляется при движении карты */}
      {prices.length > 0 && (
        <section className="mb-8 md:mb-12">
          <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-1 mb-3 md:mb-4">
            <div className="flex flex-col">
              <h2 className="text-xl md:text-2xl font-bold text-slate-900">Цены в аптеках</h2>
              {med.prices_updated_at && (
                <div className="text-[11px] md:text-xs text-slate-400 mt-0.5">
                  Цены обновлены: {(() => {
                    const d = new Date(med.prices_updated_at);
                    const months = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
                    return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()} г.`;
                  })()}
                </div>
              )}
            </div>
            <div className="text-xs md:text-sm text-slate-500">
              {viewportList.length > 0
                ? `Аптек в зоне карты: ${viewportList.length} · сначала дешевле`
                : !gorzdravStoresLoaded
                  ? 'Загрузка списка аптек…'
                  : !prices.some(p => p.pharmacy_id === 'gorzdrav')
                    ? 'Препарат в подключённых аптеках не найден'
                    : 'В видимой области карты нет аптек с препаратом'}
            </div>
          </div>
          <div className="bg-white border border-slate-100 rounded-xl divide-y divide-slate-100 overflow-hidden">
            {viewportList.length === 0 && (
              <div className="px-4 py-6 text-center text-sm text-slate-500">
                {!gorzdravStoresLoaded
                  ? 'Подождите, аптеки на карте подгружаются…'
                  : !prices.some(p => p.pharmacy_id === 'gorzdrav')
                    ? 'Этот препарат пока не найден в подключённых аптеках. Попробуйте посмотреть аналоги ниже.'
                    : 'В этой области карты нет аптек с этим препаратом — отодвиньте карту или уменьшите масштаб.'}
              </div>
            )}
            {viewportList.slice(0, viewportVisible).map(item => (
              <ViewportListItem
                key={item.key}
                item={item}
                onClick={() => {
                  setSelectedId(item.key);
                  setTimeout(() => priceMapRef.current?.centerOn(item.lat, item.lng, 15), 100);
                }}
                selected={selectedId === item.key}
              />
            ))}
            {viewportVisible < viewportList.length && (
              <div className="p-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setViewportVisible(v => v + 15)}
                  className="w-full py-2.5 rounded-lg border border-emerald-300 text-emerald-700 text-sm font-semibold hover:bg-emerald-50 transition"
                >
                  Показать ещё ({viewportList.length - viewportVisible})
                </button>
                <p className="text-[11px] text-slate-400 text-center mt-2">
                  Приблизьте карту, чтобы сузить список аптек
                </p>
              </div>
            )}
          </div>
        </section>
      )}

      {/* LLM-enriched description (top-200 popular meds) */}
      {med.enrichment && (
        <section className="mb-8 md:mb-12" data-testid="enrichment-section">
          <div className="bg-white border border-slate-100 rounded-2xl p-5 md:p-8">
            <h2 className="text-xl md:text-2xl font-bold text-slate-900 mb-3">О препарате</h2>
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
          </div>
        </section>
      )}

      {/* Analogs (strict: same MNN + same form group) */}
      {med.mnn && (
        <section className={"mb-8 md:mb-12 scroll-mt-40 md:scroll-mt-32 " + (noAvailability ? "" : "hidden md:block")} data-testid="analogs-section">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-9 h-9 rounded-lg bg-emerald-50 text-emerald-700 flex items-center justify-center"><Tag className="w-5 h-5" /></div>
            <h2 className="text-xl md:text-2xl font-bold text-slate-900 leading-tight">Аналоги по МНН: {titleCase(med.mnn)}</h2>
          </div>
          {analogs.length > 0 ? (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 md:gap-3">
              {analogs.map(a => (
                <Link
                  key={a.slug}
                  href={`/${city.id}/preparaty/${a.slug}`}
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
          ) : (
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-5 text-sm text-slate-600">
              Других препаратов с действующим веществом{' '}
              <b>{titleCase(med.mnn)}</b>
              {med.form ? <> в форме {med.form.toLowerCase()}</> : null}
              {' '}в нашем каталоге пока не найдено.
            </div>
          )}
        </section>
      )}
    </div>
  );
}
