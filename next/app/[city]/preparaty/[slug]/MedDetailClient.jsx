'use client';
import { formatName, formatManufacturer } from "../../../../utils/text";
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ChevronRight, ChevronLeft, MapPin, Phone, Clock, Pill, ShieldAlert, Tag, PackageX, Maximize2, Minimize2, Search } from 'lucide-react';
import { useCity } from '../../../../context/CityContext';
import { Drawer as VaulDrawer } from 'vaul';
import { fetchMed, fetchAnalogs, fetchPharmacies, fetchCategories, fetchGorzdravStores, fetchGorzdravStoreDetail, fetchGorzdravStoresBulk } from '../../../../api/client';
import { medFaqItems } from '../../../../lib/schemas';
import LeadModal from '../../../../components/LeadModal';
import ReviewsSection from '../../../../components/ReviewsSection';
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
  // "5 ампул × 1 мл" — retain both the container count and its volume.
  // This is different from "5 × 1 шт", where multiplying is useful.
  const countedContainer = txt.match(/^(\d+)\s+(ампул\S*|флакон\S*|шприц\S*|картридж\S*|туб\S*)\s*[xх×]\s*(\d+(?:[\.,]\d+)?)\s*(мл|мг|мкг|г|л)\b/i);
  if (countedContainer) {
    return `${countedContainer[1]} ${countedContainer[2].toLowerCase()} × ${countedContainer[3].replace(',', '.')} ${countedContainer[4].toLowerCase()}`;
  }
  // Sachet kits often include a parenthetical composition; the total sachet
  // count is the stable, readable pack label used by the selector.
  const sachets = txt.match(/^(\d+)\s+саше\b/i);
  if (sachets) return `${sachets[1]} саше`;
  // N x <CONTAINER> по M [unit]  →  'N × M <unit>' style.
  // Covers ампулы, флаконы, шприцы, банки, блистеры, упаковки, стрипы, картриджи, тубы.
  let amp = txt.match(/^(\d+|НЕ УКАЗАНО)\s*[xх×]\s*(АМПУЛ\S*|ФЛАКОН\S*|ШПРИЦ\S*|БАНК\S*|БЛИСТЕР\S*|УПАКОВК\S*|СТРИП\S*|КАРТРИДЖ\S*|ТУБ\S*)[^\d]*\s*по\s*(\d+(?:[\.,]\d+)?)\s*(?:тысяч.?\s*)?(\S+)?/i);
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
    let solo = txt.match(/^(АМПУЛ\S*|ФЛАКОН\S*|ШПРИЦ\S*|БАНК\S*|БЛИСТЕР\S*|УПАКОВК\S*|СТРИП\S*|КАРТРИДЖ\S*|ТУБ\S*)[^\d]*\s*по\s*(\d+(?:[\.,]\d+)?)\s*(\S+)?/i);
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
// Число взведённых битов в store_bitmap (base64) = сколько аптек сети реально
// имеют препарат. Используется для счётчика «в N аптеках», чтобы он совпадал
// с числом маркеров на карте (там тоже идём по битам store_bitmap).
function popcountBitmap(b64) {
  const mask = decodeBitmap(b64);
  if (!mask) return 0;
  let n = 0;
  for (let i = 0; i < mask.length; i++) {
    let v = mask[i];
    while (v) { v &= v - 1; n++; }
  }
  return n;
}

// Разбор телефона аптеки в массив { display, tel } — отдельная tap-ссылка на
// каждый номер. Ригла отдаёт «+74952311697 доб.1981/1302\n+74991585248»:
// общий номер с добавочным (несколько через «/» — берём ТОЛЬКО первый) и
// отдельный прямой номер на новой строке. Горздрав/36,6 — один обычный номер
// без добавочного (вернётся единственная запись). Добавочный кодируем паузой
// «,» в tel: — набиратель введёт его как extension, а не слитной цифрой.
function parsePhones(raw) {
  if (!raw) return [];
  return String(raw)
    .split(/[\n;]+/)
    .map(s => s.trim())
    .filter(Boolean)
    .map(part => {
      const extMatch = part.match(/доб\.?\s*([\d/]+)/i);
      const ext = extMatch ? extMatch[1].split('/')[0].trim() : '';
      const base = part.replace(/доб\.?\s*[\d/]+/i, '').replace(/[^+\d]/g, '');
      if (!base) return null;
      return {
        display: ext ? `${base} доб. ${ext}` : base,
        tel: ext ? `${base},${ext}` : base,
      };
    })
    .filter(Boolean);
}

const PriceMap = React.forwardRef(function PriceMap({ med, prices, pharmacies, gorzdravStores = [], gorzdravPrice = null, gorzdravBitmap = null, apteka366Price = null, apteka366Bitmap = null, riglaPrice = null, riglaBitmap = null, maksavitPrice = null, maksavitBitmap = null, magnitPrice = null, magnitBitmap = null, zdoroviePrice = null, zdorovieBitmap = null, cityCenter, onSelect, selected, fullscreen = false, onInteract, onViewportChange }, externalRef) {
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
        const phones = parsePhones(phone);
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
          phones.length ? `<div class="ymap-popup__row">📞 <span>${phones.map(p => `<a href="tel:${esc(p.tel)}">${esc(p.display)}</a>`).join('<br>')}</span></div>` : '',
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

      if ((gorzdravPrice !== null || apteka366Price !== null || riglaPrice !== null || maksavitPrice !== null || magnitPrice !== null) && gorzdravStores.length > 0) {
        // Маркер только для аптек, где препарат реально есть (store_bitmap),
        // а не для всех ~1900 точек сети. Каждая сеть красит свои точки своей
        // ценой и своей РЕАЛЬНОЙ маской наличия (idx общий — единый реестр).
        const BRAND_MASK = {
          gorzdrav: decodeBitmap(gorzdravBitmap),
          apteka366: decodeBitmap(apteka366Bitmap),
          rigla: decodeBitmap(riglaBitmap),
          maksavit: decodeBitmap(maksavitBitmap),
          magnit: decodeBitmap(magnitBitmap),
          zdorovie: decodeBitmap(zdorovieBitmap),
        };
        const BRAND_PRICE = { gorzdrav: gorzdravPrice, apteka366: apteka366Price, rigla: riglaPrice, maksavit: maksavitPrice, magnit: magnitPrice, zdorovie: zdoroviePrice };
        const BRAND_TITLE = { gorzdrav: 'Горздрав', apteka366: 'Аптека 36,6', rigla: 'Ригла', maksavit: 'Максавит', aptechestvo: 'Аптечество', zdorovie: 'Здоровье', magnit: 'Магнит Аптека', farmakopeika: 'Фармакопейка' };
        gorzdravStores.forEach(store => {
          if (!store.lat || !store.lng) return;
          // Бренд точки: если у сети нет цены для упаковки — откатываемся на
          // Горздрав (общий пункт выдачи gz/36,6). Ригла — отдельная сеть.
          let brand = store.brand || 'gorzdrav';
          if (BRAND_PRICE[brand] == null) brand = 'gorzdrav';
          if (!bitmapHas(BRAND_MASK[brand], store.idx)) return;
          const markerPrice = BRAND_PRICE[brand];
          if (markerPrice == null) return;
          const markerTitle = BRAND_TITLE[brand] || 'Горздрав';
          const m = L.marker([store.lat, store.lng], { icon: pillIcon(markerPrice) });
          // Лёгкий placeholder-popup (название + цена + кнопки маршрута).
          // Адрес, часы, телефон — догружаются по клику и подменяют popup.
          m.bindPopup(popupContent({
            title: markerTitle,
            address: null,
            hours: null,
            phone: null,
            price: markerPrice,
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
                title: brand === 'magnit' ? markerTitle : (full.full_name || markerTitle),
                address: full.address,
                hours: full.is_24h ? 'Круглосуточно' : full.hours,
                phone: full.phone,
                price: markerPrice,
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
  }, [med?.slug, cityCenter[0], cityCenter[1], prices.length, gorzdravStores.length, gorzdravPrice, gorzdravBitmap, apteka366Price, apteka366Bitmap, riglaPrice, riglaBitmap, maksavitPrice, maksavitBitmap, magnitPrice, magnitBitmap, zdoroviePrice, zdorovieBitmap, fullscreen]);

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
  const phones = parsePhones(item.phone);
  return (
    <div
      className={`px-4 py-3 active:bg-slate-50 transition ${selected ? 'bg-emerald-50/60' : ''}`}
      data-testid="viewport-list-item"
    >
      <button type="button" onClick={onClick} className="w-full text-left flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-slate-900 text-sm leading-tight">{item.name || (item.source === 'gorzdrav' ? 'Горздрав' : item.source === 'apteka366' ? 'Аптека 36,6' : item.source === 'rigla' ? 'Ригла' : item.source === 'maksavit' ? 'Максавит' : item.source === 'aptechestvo' ? 'Аптечество' : item.source === 'zdorovie' ? 'Здоровье' : item.source === 'magnit' ? 'Магнит Аптека' : item.source === 'farmakopeika' ? 'Фармакопейка' : 'Аптека')}</div>
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
          {phones.length > 0 && (
            <div className="text-[11px] mt-0.5 flex items-center gap-1 flex-wrap">
              <Phone className="w-3 h-3 shrink-0 text-emerald-700" />
              {phones.map((p, i) => (
                <React.Fragment key={i}>
                  {i > 0 && <span className="text-slate-300">·</span>}
                  <a href={`tel:${p.tel}`} onClick={(e) => e.stopPropagation()} className="text-emerald-700 font-medium">{p.display}</a>
                </React.Fragment>
              ))}
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

// Модалка «Заявка на поиск лекарства». ПД уходят письмом на info@aptekaa.ru
// и НИГДЕ не сохраняются. Открывается с карточки «препарата нет в аптеках».
export default function MedDetail({ initialMed = null, initialCategories = [] }) {
  const { slug, city: cityParam } = useParams();
  const { city: ctxCity, cities, setCity } = useCity();
  // Город из URL до гидрации, затем из контекста — см. шапку файла фикса.
  const [_hydrated, _setHydrated] = useState(false);
  useEffect(() => { _setHydrated(true); }, []);
  const _urlCity = cityParam ? cities.find(c => c.id === cityParam) : null;
  const city = (!_hydrated && _urlCity) ? _urlCity : ctxCity;
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
  // CWV: карта — самый дорогой блок (Leaflet + до ~2400 точек города, длинные
  // задачи 6-11с загрузки = TBT). Монтируем её и грузим реестр аптек только
  // когда пользователь доскроллил (сентинел-заглушка той же высоты -> CLS 0).
  // Боту карта не видна и раньше (client-only) — SEO не меняется.
  const [mapWanted, setMapWanted] = useState(false);
  const mapSentinelRef = useRef(null);
  useEffect(() => {
    if (mapWanted) return;
    const el = mapSentinelRef.current;
    if (!el || typeof IntersectionObserver === 'undefined') { setMapWanted(true); return; }
    const io = new IntersectionObserver((entries) => {
      if (entries.some(e => e.isIntersecting)) { setMapWanted(true); io.disconnect(); }
    }, { rootMargin: '500px' });
    io.observe(el);
    return () => io.disconnect();
  }, [mapWanted]);
  useEffect(() => { if (mapFullscreen) setMapWanted(true); }, [mapFullscreen]);
  // Динамический список аптек, видимых на карте + 15 ближайших к центру.
  // Обновляется при каждом moveend/zoomend (debounce внутри PriceMap).
  const [viewportList, setViewportList] = useState([]);
  const [viewportVisible, setViewportVisible] = useState(15);
  const lastViewportRef = useRef(null);
  const [loading, setLoading] = useState(!initialMed);
  const [selectedPack, setSelectedPack] = useState(null);
  const [notFound, setNotFound] = useState(false);
  const [leadOpen, setLeadOpen] = useState(false);
  const [categories, setCategories] = useState(initialCategories);
  // categories нужны для названия категории в лиде и хлебных крошках. Приходят
  // из SSR (initialCategories) → на сервере и клиенте одинаковы, без hydration
  // mismatch. Дозагружаем только если сервер их не передал (SPA-навигация).
  useEffect(() => { if (!initialCategories.length) fetchCategories(cityParam).then(setCategories).catch(() => {}); }, [cityParam, initialCategories.length]);

  // Sync URL city → context
  useEffect(() => {
    if (cityParam && cities) {
      const found = cities.find(c => c.id === cityParam);
      if (found && found.id !== ctxCity.id) setCity(found);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cityParam]);

  useEffect(() => {
    let cancelled = false;
    // Если нет initialMed (SPA-навигация между препаратами) — показываем спиннер.
    // При первом маунте с SSR-данными loading уже false, не перезатираем.
    if (!med) setLoading(true);
    setNotFound(false);
    Promise.all([fetchMed(slug, city.id), fetchAnalogs(slug, 8), fetchPharmacies(city.id)])
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

  // Реестр аптек города (до ~2400 точек) — только когда карта затребована
  // (mapWanted): его загрузка+обработка порождала длинные задачи при старте.
  useEffect(() => {
    if (!mapWanted) return;
    let cancelled = false;
    setGorzdravStoresLoaded(false);
    fetchGorzdravStores(city.id)
      .then(gz => { if (!cancelled) setGorzdravStores(gz); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setGorzdravStoresLoaded(true); });
    return () => { cancelled = true; };
  }, [mapWanted, city.id]);

  // Unique pack list (computed once per med).
  const packs = useMemo(() => {
    if (!med?.variants) return [];
    return sortPacks([...new Set(med.variants.map(v => simplifyPack(v.pack_size)).filter(Boolean))]);
  }, [med]);

  // Упаковки, для которых у Горздрав есть реальные данные — приоритет дефолта.
  const inStockPacks = useMemo(() => {
    const rows = (med?.prices_by_city?.[city.id] || [])
      .filter(p => p.availability_confirmed === true && p.store_bitmap);
    return new Set(packs.filter(pack => rows.some(row => packMatchesOffer(pack, row))));
  }, [med, city.id, packs]);

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

  function extractGzPack(name) {
    if (!name) return null;
    const m = String(name).match(/(\d+(?:[\.,]\d+)?)\s*(шт|мл|мг|мкг|г|л)\b[^\d]*$/i);
    if (!m) return null;
    return `${m[1].replace(',', '.')} ${m[2].toLowerCase()}`;
  }

  function packMatchesOffer(approvedPack, row) {
    if (!approvedPack || !row) return false;
    // Priority catalogue rows are admitted only after backend verification
    // against their single approved variant (dose, form, maker and pack).
    if (row.identity_verified === true) return true;
    const approved = simplifyPack(approvedPack);
    const actual = row.gz_pack || row.pack_size || extractGzPack(row.gz_name);
    if (!actual) return false;
    if (packTotal(actual) === packTotal(approved)) return true;
    const inner = approved.match(/[×xх]\s*(\d+(?:[.,]\d+)?)\s*(мл|мг|мкг|г|л)\b/i);
    const outer = approved.match(/^\s*(\d+(?:[.,]\d+)?)/);
    const actualPart = String(actual).match(/^\s*(\d+(?:[.,]\d+)?)\s*([а-яa-z]+)/i);
    if (!inner || !outer || !actualPart) return false;
    const innerNumber = inner[1].replace(',', '.');
    const innerUnit = inner[2].toLowerCase();
    const actualNumber = actualPart[1].replace(',', '.');
    const actualUnit = actualPart[2].toLowerCase();
    const title = String(row.gz_name || row.pack_size || '').toLowerCase().replace(',', '.');
    const escapedNumber = innerNumber.replace('.', '\\.');
    const titleHasInner = new RegExp(`(^|[^\\d.])${escapedNumber}(?![\\d.])\\s*${innerUnit}`).test(title);
    const outerMatches = Number(outer[1].replace(',', '.')) === Number(actualNumber);
    const innerMatches = Number(innerNumber) === Number(actualNumber) && innerUnit === actualUnit;
    return titleHasInner && (outerMatches || innerMatches);
  }

  const priceRows = useMemo(() => {
    if (!med) return [];
    const all = [...((med.prices_by_city || {})[city.id] || [])];
    // Показываем только реально полученные строки. Цены для другой фасовки
    // скрываем; расчётных и масштабированных цен на сайте нет.
    const REAL_SOURCES = ['gorzdrav', 'apteka366', 'rigla', 'maksavit', 'aptechestvo', 'zdorovie', 'magnit', 'farmakopeika', 'uteka', 'eapteka', 'zdravcity', 'asna', 'aptekamos'];
    // price>0: 0 = сматчено, но цены/наличия нет — такую сеть не показываем
    // (иначе на упаковке с единственной 0-строкой она всплывала как «0 ₽ дешевле»).
    const networkAll = all.filter(p => REAL_SOURCES.includes(p.pharmacy_id) && p.price > 0);
    const networks = activePack
      ? networkAll.filter(p => packMatchesOffer(activePack, p))
      : networkAll;
    const directAll = all.filter(p => !REAL_SOURCES.includes(p.pharmacy_id) && p.price > 0);
    // Загруженные аптекой строки без указанной фасовки нельзя безопасно
    // размножать по нескольким вариантам одной карточки.
    const direct = activePack && packs.length > 1
      ? directAll.filter(p => packMatchesOffer(activePack, p))
      : directAll;
    return [...direct, ...networks].sort((a, b) => a.price - b.price);
  }, [med, city.id, packs, activePack]);

  const prices = useMemo(
    () => priceRows.filter(p => p.availability_confirmed === true),
    [priceRows],
  );
  const historicalPrices = useMemo(
    () => priceRows.filter(p => p.availability_confirmed !== true),
    [priceRows],
  );

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
    const BRAND_PRICE = {
      gorzdrav: prices.find(p => p.pharmacy_id === 'gorzdrav')?.price ?? null,
      apteka366: prices.find(p => p.pharmacy_id === 'apteka366')?.price ?? null,
      rigla: prices.find(p => p.pharmacy_id === 'rigla')?.price ?? null,
      maksavit: prices.find(p => p.pharmacy_id === 'maksavit')?.price ?? null,
      magnit: prices.find(p => p.pharmacy_id === 'magnit')?.price ?? null,
      zdorovie: prices.find(p => p.pharmacy_id === 'zdorovie')?.price ?? null,
    };

    // 1. Партнёрские аптеки в bbox + у них есть цена для активной упаковки.
    const partnerEntries = prices
      .map(pr => {
        if (pr.pharmacy_id === 'gorzdrav' || pr.pharmacy_id === 'apteka366' || pr.pharmacy_id === 'rigla' || pr.pharmacy_id === 'maksavit' || pr.pharmacy_id === 'magnit') return null;
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

    // 2. Сетевые аптеки в bbox, где препарат реально есть (store_bitmap).
    //    Каждая сеть — своя маска + своя цена (idx общий, единый реестр).
    const BRAND_MASK = {
      gorzdrav: decodeBitmap(prices.find(p => p.pharmacy_id === 'gorzdrav')?.store_bitmap),
      apteka366: decodeBitmap(prices.find(p => p.pharmacy_id === 'apteka366')?.store_bitmap),
      rigla: decodeBitmap(prices.find(p => p.pharmacy_id === 'rigla')?.store_bitmap),
      maksavit: decodeBitmap(prices.find(p => p.pharmacy_id === 'maksavit')?.store_bitmap),
      magnit: decodeBitmap(prices.find(p => p.pharmacy_id === 'magnit')?.store_bitmap),
      zdorovie: decodeBitmap(prices.find(p => p.pharmacy_id === 'zdorovie')?.store_bitmap),
    };
    const gzCandidates = gorzdravStores
      .filter(s => s.lat >= bounds.south && s.lat <= bounds.north && s.lng >= bounds.west && s.lng <= bounds.east)
      .map(s => {
        // Бренд точки; без цены сети — откат на Горздрав (общий пункт gz/36,6).
        let brand = s.brand || 'gorzdrav';
        if (BRAND_PRICE[brand] == null) brand = 'gorzdrav';
        if (!bitmapHas(BRAND_MASK[brand], s.idx)) return null;
        const price = BRAND_PRICE[brand];
        if (price == null) return null;
        return {
          key: 'gorzdrav_' + s.store_id,
          source: brand,
          store_id: s.store_id,
          lat: s.lat,
          lng: s.lng,
          price,
          distance: haversine(center.lat, center.lng, s.lat, s.lng),
        };
      })
      .filter(Boolean);

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
      .filter(x => (x.source === 'gorzdrav' || x.source === 'apteka366' || x.source === 'rigla' || x.source === 'maksavit' || x.source === 'magnit') && !x.name)
      .map(x => x.store_id);
    if (need.length === 0) return;
    let cancelled = false;
    fetchGorzdravStoresBulk(need).then(details => {
      if (cancelled) return;
      const byId = Object.fromEntries(details.map(d => [d.store_id, d]));
      setViewportList(prev => prev.map(item => {
        if ((item.source === 'gorzdrav' || item.source === 'apteka366' || item.source === 'rigla' || item.source === 'maksavit' || item.source === 'magnit') && !item.name && byId[item.store_id]) {
          const d = byId[item.store_id];
          return {
            ...item,
            name: item.source === 'magnit' ? 'Магнит Аптека' : (d.full_name || (item.source === 'apteka366' ? 'Аптека 36,6' : item.source === 'rigla' ? 'Ригла' : item.source === 'maksavit' ? 'Максавит' : 'Горздрав')),
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

  const historicalByNetwork = Object.values(historicalPrices.reduce((acc, row) => {
    const key = row.pharmacy_id || 'source';
    const previous = acc[key];
    if (!previous || String(row.observed_at || '') > String(previous.observed_at || '')) acc[key] = row;
    return acc;
  }, {})).sort((a, b) => a.price - b.price);
  const minPrice = prices.length ? Math.min(...prices.map(p => p.price)) : null;
  const maxPrice = prices.length ? Math.max(...prices.map(p => p.price)) : null;
  const lastPrice = historicalByNetwork.length ? Math.min(...historicalByNetwork.map(p => p.price)) : null;
  const lastPriceRows = lastPrice == null
    ? []
    : historicalByNetwork.filter(p => p.price === lastPrice);
  const lastObservedAt = lastPriceRows
    .map(p => p.observed_at)
    .filter(Boolean)
    .sort()
    .at(-1) || null;
  const currentObservedAt = prices
    .map(p => p.observed_at)
    .filter(Boolean)
    .sort()
    .at(-1) || null;
  const formatObservedDate = (value) => {
    if (!value) return null;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    return new Intl.DateTimeFormat('ru-RU', {
      day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'Europe/Moscow',
    }).format(date);
  };
  const lastObservedDate = formatObservedDate(lastObservedAt);
  // Число аптек = popcount store_bitmap по каждой сети (как на карте: маркер
  // ставится на каждый взведённый бит). Так заголовок «в N аптеках» совпадает
  // с числом точек на карте. Откат: Горздрав → qty (= число аптек), прочие → 1,
  // если битмапа нет (старые/синтетические записи).
  const totalPharmacyCount = prices.reduce((sum, p) => {
    const fromBitmap = popcountBitmap(p.store_bitmap);
    if (fromBitmap > 0) return sum + fromBitmap;
    return sum + (p.pharmacy_id === 'gorzdrav' ? (p.qty || 0) : 0);
  }, 0);
  
  // Сети без по-аптечных координат (Магнит/Аптечество/Здоровье) — нет адресов
  // отдельных точек; показываем как сеть, а не как «1 аптеку» с пустой картой.
  const NET_NAMES_ALL = { gorzdrav: 'Горздрав', apteka366: 'Аптека 36,6', rigla: 'Ригла', maksavit: 'Максавит', aptechestvo: 'Аптечество', zdorovie: 'Здоровье', magnit: 'Магнит Аптека', farmakopeika: 'Фармакопейка', uteka: 'Ютека', eapteka: 'ЕАПТЕКА', zdravcity: 'Здравсити', asna: 'АСНА', aptekamos: 'АптекаМос' };
  const networkNames = [...new Set(prices.filter(p => NET_NAMES_ALL[p.pharmacy_id] && p.price > 0).map(p => NET_NAMES_ALL[p.pharmacy_id]))];
  const networkStr = networkNames.length <= 1 ? (networkNames[0] || '') : networkNames.slice(0, -1).join(', ') + ' и ' + networkNames.slice(-1);
  const networkWord = networkNames.length > 1 ? 'в сетях' : 'в сети';
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

      <div id="harakteristiki" className="grid lg:grid-cols-[380px_1fr] gap-6 md:gap-8 mb-8 md:mb-10 scroll-mt-32">
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
            {med.dosage && <span className="text-slate-800">, {med.dosage}</span>}
            {med.seo?.title_qualifier && <span className="text-slate-700">, {formatManufacturer(med.seo.title_qualifier)}</span>}
          </h1>
          <p className="text-slate-600 mt-0.5">{formLower}</p>

          {/* Лид-абзац (SEO): keyword + город + условное «сравните» по числу
              сетей с ценой + in-content ссылка на категорию (перелинковка). */}
          {(() => {
            const nm = formatName(med.name);
            const NET_NAMES = { gorzdrav: 'Горздрав', apteka366: 'Аптека 36,6', rigla: 'Ригла', maksavit: 'Максавит', aptechestvo: 'Аптечество', zdorovie: 'Здоровье', magnit: 'Магнит Аптека', farmakopeika: 'Фармакопейка' };
            const nets = new Set(prices.map(p => p.pharmacy_id).filter(id => NET_NAMES[id]));
            const multi = nets.size >= 2;
            const netNames = [...nets].map(id => NET_NAMES[id]).filter(Boolean);
            const netStr = netNames.length <= 1 ? (netNames[0] || '') : netNames.slice(0, -1).join(', ') + ' и ' + netNames.slice(-1);
            const priceStr = minPrice == null ? null : (minPrice === maxPrice ? `${minPrice}\u00a0\u20bd` : `от\u00a0${minPrice} до\u00a0${maxPrice}\u00a0\u20bd`);
            const catTitle = (med.category && med.category !== 'other')
              ? ((categories.find(c => c.slug === med.category) || {}).title || null)
              : null;
            return (
              <p className="text-slate-600 mt-3 text-sm leading-relaxed max-w-3xl" data-testid="med-lead">
                {nm} — {formLower}{med.mnn ? <>, действующее вещество {titleCase(med.mnn)}</> : null}
                {catTitle ? <> из категории <Link href={`/${city.id}/kategorii/${med.category}`} className="text-emerald-700 hover:underline">{catTitle.toLowerCase()}</Link></> : null}.{' '}
                {med.geo && med.geo.count > 0
                  ? <>В {city.inLoc} есть в {med.geo.count}&nbsp;{med.geo.count === 1 ? 'аптеке' : 'аптеках'} от {med.geo.min_price}&nbsp;₽{multi ? <> — сравните цены в сетях {netStr}</> : null}. Проверьте наличие в ближайших аптеках на карте ниже.</>
                  : priceStr
                  ? (multi
                      ? <>Сравните цены в аптечных сетях {netStr} в {city.inLoc}: {priceStr} — и проверьте наличие в ближайших аптеках на карте.</>
                      : <>Цена в {city.inLoc}: {priceStr}. Проверьте наличие в ближайших аптеках на карте.</>)
                  : lastPrice != null
                  ? <>Последняя зафиксированная цена в {city.inLoc} — от&nbsp;{lastPrice}&nbsp;₽{lastObservedDate ? <> на {lastObservedDate}</> : null}. Текущую стоимость и наличие уточняйте в аптеке.</>
                  : <>Посмотрите аналоги и проверьте наличие в аптеках на карте.</>}
              </p>
            );
          })()}

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
                  <>от&nbsp;{minPrice}&nbsp;₽ до&nbsp;{maxPrice}&nbsp;₽{totalPharmacyCount > 0 ? <> · в&nbsp;{totalPharmacyCount}&nbsp;аптеках</> : (networkStr ? <> · {networkWord} {networkStr}</> : null)}</>
                ) : (
                  totalPharmacyCount > 0 ? <>в&nbsp;{totalPharmacyCount}&nbsp;аптеках</> : (networkStr ? <>{networkWord} {networkStr}</> : null)
                )}
              </div>
            </div>
          )}

          {minPrice === null && lastPrice !== null && (
            <div className="mt-6 bg-amber-50/60 border border-amber-200 rounded-xl p-5" data-testid="historical-price">
              <div className="text-xs font-medium text-amber-900">Последняя зафиксированная цена в {city.inLoc}</div>
              <div className="text-3xl font-extrabold text-slate-900 whitespace-nowrap">
                от&nbsp;{lastPrice}&nbsp;₽
              </div>
              <div className="text-sm text-slate-600 mt-1">
                {lastObservedDate ? <>Данные на {lastObservedDate}. </> : null}
                Сейчас наличие не подтверждено; стоимость и возможность заказа уточняйте в аптеке.
              </div>
            </div>
          )}

          {/* Гео-блок (SEO #1: локальный контент). Реальные адреса аптек города,
              где препарат есть. Данные из med.geo (бэкенд, городской уровень) →
              видны в SSR-HTML боту, уникальны по каждому городу. */}
          {med.geo && Array.isArray(med.geo.stores) && med.geo.stores.length > 0 && (
            <div className="mt-6 bg-white border border-slate-200 rounded-xl p-5" data-testid="geo-block">
              <div className="flex items-center gap-2 text-base font-semibold text-slate-900">
                <MapPin className="w-5 h-5 text-emerald-600 shrink-0" />
                Где купить в {city.inLoc}
              </div>
              <p className="text-sm text-slate-600 mt-1">
                {formatName(med.name)} есть в {med.geo.count}&nbsp;{med.geo.count === 1 ? 'аптеке' : 'аптеках'} города. Например:
              </p>
              <div className="mt-3 divide-y divide-slate-100">
                {med.geo.stores.map((s, i) => (
                  <div key={i} className="flex items-baseline justify-between gap-3 py-2">
                    <div className="min-w-0">
                      <div className="text-sm text-slate-800">{s.address}</div>
                      {NET_NAMES_ALL[s.brand] && <div className="text-xs text-slate-400">{NET_NAMES_ALL[s.brand]}</div>}
                    </div>
                    {typeof s.price === 'number' && (
                      <div className="text-sm font-medium text-slate-900 whitespace-nowrap">{s.price}&nbsp;₽</div>
                    )}
                  </div>
                ))}
              </div>
              {med.geo.count > med.geo.stores.length && (
                <p className="mt-3 text-xs text-slate-400">Все {med.geo.count}&nbsp;аптек с этим препаратом — на карте ниже.</p>
              )}
            </div>
          )}

          {/* Сравнение цен по аптечным сетям (Горздрав vs Аптека 36,6).
              Показываем только когда есть >=2 сети с ценой для активной
              упаковки — иначе сравнивать нечего. */}
          {(() => {
            const NET_LABELS = { gorzdrav: 'Горздрав', apteka366: 'Аптека 36,6', rigla: 'Ригла', maksavit: 'Максавит', aptechestvo: 'Аптечество', zdorovie: 'Здоровье', magnit: 'Магнит Аптека', farmakopeika: 'Фармакопейка' };
            const byNet = {};
            for (const p of prices) {
              if (!NET_LABELS[p.pharmacy_id]) continue;
              if (byNet[p.pharmacy_id] == null || p.price < byNet[p.pharmacy_id]) {
                byNet[p.pharmacy_id] = p.price;
              }
            }
            const rows = Object.entries(byNet)
              .map(([id, price]) => ({ id, price, name: NET_LABELS[id] }))
              .sort((a, b) => a.price - b.price);
            if (rows.length < 2) return null;
            const best = rows[0].price;
            return (
              <div className="mt-4 bg-white border border-slate-200 rounded-xl p-4" data-testid="network-price-compare">
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                  Сравнение цен по сетям{activePack ? ` · ${activePack}` : ''}
                </div>
                <div className="divide-y divide-slate-100">
                  {rows.map(r => (
                    <div key={r.id} className="flex items-center justify-between py-2">
                      <span className="text-sm font-medium text-slate-800">{r.name}</span>
                      <span className="flex items-center gap-2">
                        {r.price === best && rows.some(x => x.price > best) && (
                          <span className="text-[10px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-full px-2 py-0.5">дешевле</span>
                        )}
                        <span className={`text-base font-bold ${r.price === best ? 'text-emerald-700' : 'text-slate-700'}`}>
                          {r.price}&nbsp;₽
                        </span>
                      </span>
                    </div>
                  ))}
                </div>
                <div className="text-[11px] text-slate-400 mt-2">Цены сетей могут отличаться от цен в конкретной аптеке.</div>
              </div>
            );
          })()}

          {totalPharmacyCount === 0 && networkNames.length >= 1 && (
            <div className="mt-4 bg-white border border-slate-200 rounded-xl p-4" data-testid="network-only-note">
              <div className="text-sm text-slate-700 leading-relaxed">
                Наличие в {networkNames.length > 1 ? 'сетях' : 'сети'} <b>{networkStr}</b> — цена указана по&nbsp;{city.inLoc}. Адреса конкретных аптек и точный остаток уточняйте на&nbsp;сайте сети.
              </div>
            </div>
          )}

          {prices.length === 0 && historicalByNetwork.length > 0 && (
            <div id="poslednyaya-tsena" className="mt-4 bg-white border border-amber-200 rounded-xl p-4 scroll-mt-32" data-testid="historical-price-sources">
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                Последние цены в других аптеках{activePack ? ` · ${activePack}` : ''}
              </div>
              <div className="divide-y divide-slate-100">
                {historicalByNetwork.map((row, index) => (
                  <div key={`${row.pharmacy_id || 'source'}-${index}`} className="flex items-start justify-between gap-3 py-2">
                    <div>
                      <div className="text-sm font-medium text-slate-800">{NET_NAMES_ALL[row.pharmacy_id] || row.pharmacy_id || 'Аптечная сеть'}</div>
                      <div className="text-[11px] text-slate-500">
                        {formatObservedDate(row.observed_at) ? `зафиксировано ${formatObservedDate(row.observed_at)}` : 'дата фиксации не указана'}
                      </div>
                    </div>
                    <div className="text-base font-bold text-slate-800 whitespace-nowrap">{row.price}&nbsp;₽</div>
                  </div>
                ))}
              </div>
              <p className="text-[11px] text-slate-500 mt-2">Это справочные исторические данные, а не действующее предложение. Наличие и текущую цену уточняйте в аптеке.</p>
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
              <div className="mt-3">
                <button
                  data-testid="lead-open-btn"
                  onClick={() => setLeadOpen(true)}
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-red-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-red-700 transition-colors md:inline-flex md:w-auto"
                >
                  <Search className="w-4 h-4 shrink-0" />
                  Оставить заявку на поиск лекарства
                </button>
                <p className="text-xs text-slate-500 mt-1.5 text-center md:text-left">
                  Найдём препарат в ближайшей к вам аптеке и сообщим, где он есть.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>

      <nav aria-label="Содержание страницы" className="mb-8 rounded-xl border border-slate-200 bg-white p-4" data-testid="med-toc">
        <div className="text-sm font-semibold text-slate-900 mb-2">На странице</div>
        <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
          <a href="#harakteristiki" className="text-emerald-700 hover:underline">Характеристики</a>
          {prices.length > 0 && <a href="#nalichie" className="text-emerald-700 hover:underline">Цены и наличие в {city.inLoc}</a>}
          {prices.length === 0 && historicalPrices.length > 0 && <a href="#poslednyaya-tsena" className="text-emerald-700 hover:underline">Последняя зафиксированная цена</a>}
          {med.enrichment && <a href="#o-preparate" className="text-emerald-700 hover:underline">О препарате</a>}
          {med.mnn && <a href="#analogi" className="text-emerald-700 hover:underline">Аналоги</a>}
          <a href="#voprosy" className="text-emerald-700 hover:underline">Вопросы и ответы</a>
        </div>
      </nav>

      {/* Map — только когда есть аптеки с координатами. Сети без адресов точек
          (Магнит и пр.) карту не показывают — вместо неё карточка сети выше. */}
      {totalPharmacyCount > 0 && (
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
            {!mapWanted && (
              <div
                ref={mapSentinelRef}
                data-testid="map-placeholder"
                className="w-full h-[360px] md:h-[460px] rounded-xl overflow-hidden border border-slate-100 bg-slate-50 flex items-center justify-center text-sm text-slate-400"
              >
                Карта аптек загрузится при прокрутке…
              </div>
            )}
            {mapWanted && <PriceMap
              ref={priceMapRef}
              med={med}
              prices={prices}
              pharmacies={pharmacies}
              gorzdravStores={gorzdravStores}
              gorzdravPrice={prices.find(p => p.pharmacy_id === 'gorzdrav')?.price ?? null}
              gorzdravBitmap={prices.find(p => p.pharmacy_id === 'gorzdrav')?.store_bitmap ?? null}
              apteka366Price={prices.find(p => p.pharmacy_id === 'apteka366')?.price ?? null}
              apteka366Bitmap={prices.find(p => p.pharmacy_id === 'apteka366')?.store_bitmap ?? null}
              riglaPrice={prices.find(p => p.pharmacy_id === 'rigla')?.price ?? null}
              riglaBitmap={prices.find(p => p.pharmacy_id === 'rigla')?.store_bitmap ?? null}
              maksavitPrice={prices.find(p => p.pharmacy_id === 'maksavit')?.price ?? null}
              maksavitBitmap={prices.find(p => p.pharmacy_id === 'maksavit')?.store_bitmap ?? null}
              magnitPrice={prices.find(p => p.pharmacy_id === 'magnit')?.price ?? null}
              magnitBitmap={prices.find(p => p.pharmacy_id === 'magnit')?.store_bitmap ?? null}
              zdoroviePrice={prices.find(p => p.pharmacy_id === 'zdorovie')?.price ?? null}
              zdorovieBitmap={prices.find(p => p.pharmacy_id === 'zdorovie')?.store_bitmap ?? null}
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
            />}
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
        <section id="nalichie" className="mb-8 md:mb-12 scroll-mt-32">
          <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-1 mb-3 md:mb-4">
            <div className="flex flex-col">
              <h2 className="text-xl md:text-2xl font-bold text-slate-900">Цены в аптеках</h2>
              {currentObservedAt && (
                <div className="text-[11px] md:text-xs text-slate-400 mt-0.5">
                  Цены обновлены: {(() => {
                    const d = new Date(currentObservedAt);
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
                  : !prices.some(p => ['gorzdrav','apteka366','rigla','maksavit'].includes(p.pharmacy_id))
                    ? 'Препарат в подключённых аптеках не найден'
                    : 'В видимой области карты нет аптек с препаратом'}
            </div>
          </div>
          <div className="bg-white border border-slate-100 rounded-xl divide-y divide-slate-100 overflow-hidden">
            {viewportList.length === 0 && (
              <div className="px-4 py-6 text-center text-sm text-slate-500">
                {!gorzdravStoresLoaded
                  ? 'Подождите, аптеки на карте подгружаются…'
                  : !prices.some(p => ['gorzdrav','apteka366','rigla','maksavit'].includes(p.pharmacy_id))
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

      {/* Reviewed reference content: indications, precautions and sources. */}
      {med.enrichment && (
        <section id="o-preparate" className="mb-8 md:mb-12 scroll-mt-32" data-testid="enrichment-section">
          <div className="bg-white border border-slate-100 rounded-2xl p-5 md:p-8">
            <h2 className="text-xl md:text-2xl font-bold text-slate-900 mb-3">О препарате</h2>
            {/* SEO #1: городской абзац — уникальный локальный текст в самом
                крупном блоке страницы (тело «О препарате» иначе идентично по всем
                12 городам → «малоценность»). Данные из med.geo/prices, рендерится
                только при реальной цене города (пустые = noindex, абзац скрыт).
                Формулировки отличаются от лида и гео-блока — не дублируем. */}
            {(() => {
              const g = med.geo;
              if (!g || typeof g.min_price !== 'number') return null;
              const nm = formatName(med.name);
              const nets = [...new Set(prices.map(p => p.pharmacy_id).filter(id => NET_NAMES_ALL[id]))].map(id => NET_NAMES_ALL[id]);
              const multi = nets.length >= 2;
              const netStr = nets.length <= 1 ? (nets[0] || '') : nets.slice(0, -1).join(', ') + ' и ' + nets.slice(-1);
              const range = (typeof g.max_price === 'number' && g.max_price !== g.min_price)
                ? <>от&nbsp;{g.min_price}&nbsp;₽ до&nbsp;{g.max_price}&nbsp;₽</>
                : <>от&nbsp;{g.min_price}&nbsp;₽</>;
              const st0 = Array.isArray(g.stores) && g.stores[0] && g.stores[0].address ? g.stores[0] : null;
              const exAddr = st0 ? st0.address.replace(/^[^,]*(обл|область|край|респ|автономн)[^,]*,\s*/i, '') : null;
              return (
                <p className="text-slate-700 leading-relaxed mb-6" data-testid="med-city-about">
                  {g.count > 0
                    ? <>В {city.inLoc} {nm} представлен в {g.count}&nbsp;{g.count === 1 ? 'аптеке' : 'аптеках'} по цене {range}.</>
                    : <>В {city.inLoc} {nm} доступен по цене {range}{netStr ? <> в {nets.length > 1 ? 'сетях' : 'сети'} {netStr}</> : null}.</>}
                  {multi
                    ? <> Стоимость отличается между сетями {netStr} — на этой странице можно сравнить цены и выбрать выгодный вариант.</>
                    : (nets.length === 1 && g.count > 0 ? <> Препарат представлен в сети {netStr}.</> : null)}
                  {exAddr ? <> Например, в аптеке по адресу {exAddr}{typeof st0.price === 'number' ? <> — {st0.price}&nbsp;₽</> : null}.</> : null}
                  {' '}Актуальное наличие и адреса всех аптек — на карте выше.
                </p>
              );
            })()}
            {med.enrichment.summary && (
              <p className="text-slate-700 leading-relaxed mb-6">{med.enrichment.summary}</p>
            )}
            <div className="mb-6 overflow-hidden rounded-xl border border-slate-200" data-testid="med-facts-table">
              <h3 className="bg-slate-50 px-4 py-3 text-sm font-semibold text-slate-900">Форма выпуска и характеристики</h3>
              <dl className="grid sm:grid-cols-2 text-sm">
                {med.mnn && <div className="border-t border-slate-100 px-4 py-3"><dt className="text-slate-500">Действующее вещество</dt><dd className="mt-0.5 font-medium text-slate-900">{titleCase(med.mnn)}</dd></div>}
                {med.dosage && <div className="border-t border-slate-100 px-4 py-3"><dt className="text-slate-500">Дозировка</dt><dd className="mt-0.5 font-medium text-slate-900">{med.dosage}</dd></div>}
                {med.form && <div className="border-t border-slate-100 px-4 py-3"><dt className="text-slate-500">Лекарственная форма</dt><dd className="mt-0.5 font-medium text-slate-900">{formatName(med.form)}</dd></div>}
                {med.manufacturer && <div className="border-t border-slate-100 px-4 py-3"><dt className="text-slate-500">Производитель</dt><dd className="mt-0.5 font-medium text-slate-900">{formatManufacturer(med.manufacturer)}</dd></div>}
              </dl>
            </div>
            <div className="grid md:grid-cols-2 gap-6">
              {med.enrichment.indications?.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-emerald-800 uppercase tracking-wide mb-2">Основные области применения</h3>
                  <ul className="space-y-1.5 text-sm text-slate-700">
                    {med.enrichment.indications.map((t, i) => (
                      <li key={i} className="flex gap-2"><span className="text-emerald-500 shrink-0">•</span><span>{t}</span></li>
                    ))}
                  </ul>
                </div>
              )}
              {med.enrichment.contraindications?.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-rose-800 uppercase tracking-wide mb-2">Противопоказания и важные ограничения</h3>
                  <ul className="space-y-1.5 text-sm text-slate-700">
                    {med.enrichment.contraindications.map((t, i) => (
                      <li key={i} className="flex gap-2"><span className="text-rose-500 shrink-0">•</span><span>{t}</span></li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            {med.enrichment.medical_details_status === 'catalog-summary-only' && (
              <p className="mt-6 rounded-lg bg-slate-50 px-4 py-3 text-xs leading-relaxed text-slate-600">
                Подробные медицинские сведения не публикуются, пока к карточке не привязана инструкция именно этой упаковки. Сверяйте показания, противопоказания и способ применения по листку-вкладышу препарата.
              </p>
            )}
            {med.enrichment.how_to_take && (
              <div className="mt-6 pt-6 border-t border-slate-100">
                <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-2">Способ применения</h3>
                <p className="text-sm text-slate-700 leading-relaxed">{med.enrichment.how_to_take}</p>
              </div>
            )}
            {med.enrichment.disclaimer && (
              <p className="mt-5 rounded-lg bg-amber-50 px-4 py-3 text-xs leading-relaxed text-amber-900">{med.enrichment.disclaimer}</p>
            )}
            {med.enrichment.sources?.length > 0 && (
              <div className="mt-6 border-t border-slate-100 pt-5" data-testid="med-sources">
                <h3 className="text-sm font-semibold text-slate-900">Источники информации</h3>
                <ul className="mt-2 space-y-1.5 text-sm text-slate-600">
                  {med.enrichment.sources.map((source, i) => (
                    <li key={`${source.url}-${i}`}>
                      <a href={source.url} target="_blank" rel="noopener noreferrer" className="text-emerald-700 hover:underline">{source.title}</a>
                    </li>
                  ))}
                </ul>
                {med.enrichment.updated_at && <p className="mt-2 text-xs text-slate-400">Материал обновлён: {med.enrichment.updated_at.split('-').reverse().join('.')}.</p>}
              </div>
            )}
          </div>
        </section>
      )}

      {/* Analogs (strict: same MNN + same form group) */}
      {med.mnn && (
        <section id="analogi" className="mb-8 md:mb-12 scroll-mt-40 md:scroll-mt-32" data-testid="analogs-section">
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

      {/* FAQ — частые вопросы. Контент совпадает с FAQPage JSON-LD (page.jsx),
          чтобы разметка соответствовала видимому тексту (требование Яндекса). */}
      {(() => {
        // Город из URL (useParams), НЕ из useCity() — контекст на сервере
        // дефолтит на msk, что ломало SSR-FAQ для SPB (несовпадение с JSON-LD).
        const faq = medFaqItems(cityParam || city.id, med);
        if (!faq.length) return null;
        return (
          <section id="voprosy" className="mb-8 md:mb-12 scroll-mt-32" data-testid="faq-section">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-9 h-9 rounded-lg bg-emerald-50 text-emerald-700 flex items-center justify-center"><Pill className="w-5 h-5" /></div>
              <h2 className="text-xl md:text-2xl font-bold text-slate-900 leading-tight">Частые вопросы</h2>
            </div>
            <div className="divide-y divide-slate-100 bg-white border border-slate-200 rounded-xl">
              {faq.map((it, i) => (
                <details key={i} className="group px-4 py-3" {...(i === 0 ? { open: true } : {})}>
                  <summary className="cursor-pointer list-none flex items-center justify-between gap-3 font-semibold text-slate-900 text-sm md:text-base">
                    <span>{it.q}</span>
                    <ChevronRight className="w-4 h-4 shrink-0 text-slate-400 transition group-open:rotate-90" />
                  </summary>
                  <p className="text-sm text-slate-600 leading-relaxed mt-2">{it.a}</p>
                </details>
              ))}
            </div>
          </section>
        );
      })()}

      {/* Отзывы о препарате (UGC). Один пул на канонический препарат (slug),
          общий для всех городов. Блок и звёзды-schema — только при ≥1 отзыве. */}
      <ReviewsSection slug={slug} initialReviews={med && med.reviews} />

      {/* Перелинковка между городами — SEO discovery + внутренний PageRank.
          Один и тот же препарат есть во всех городах (slug общий, отличаются
          цены/наличие). Помогает ботам обойти гео-варианты и юзеру сменить город. */}
      {med && cities && cities.filter(c => c.id !== city.id && med.seo_indexable_by_city?.[c.id]).length > 0 && (
        <section className="mb-8 md:mb-12" data-testid="other-cities-section">
          <h2 className="text-lg md:text-xl font-bold text-slate-900 mb-3">{formatName(med.name)} в других городах</h2>
          <div className="flex flex-wrap gap-2">
            {cities.filter(c => c.id !== city.id && med.seo_indexable_by_city?.[c.id]).map(c => (
              <Link
                key={c.id}
                href={`/${c.id}/preparaty/${slug}`}
                className="px-3 py-1.5 rounded-lg border border-slate-200 text-sm text-slate-700 hover:border-emerald-300 hover:text-emerald-700 transition"
              >
                {c.name}
              </Link>
            ))}
          </div>
        </section>
      )}

      <LeadModal
        open={leadOpen}
        onClose={() => setLeadOpen(false)}
        medication={med ? formatName(med.name) : ''}
        slug={slug}
        city={cityParam || (city && city.id)}
      />
    </div>
  );
}
