// Yandex Maps JS API v2.1 loader.
//
// Phase 9 audit: до этого фикса loader тянул v3 API (`api-maps.yandex.ru/v3/`),
// но наш apikey зарегистрирован для v2.1 → 403 «Invalid api key». Плюс
// consumer-код (PharmacyDetailClient.jsx) использует v2 синтаксис
// (`new ymaps.Map(...)`, `new ymaps.Placemark(...)`, `m.geoObjects.add(...)`),
// который несовместим с v3 (`new ymaps3.YMap(...)`). Карта на странице
// аптеки была разбита по двум причинам сразу.
//
// Откатили loader на v2.1; consumer-код менять не нужно.

let ymapsPromise = null;

export function loadYmaps() {
  if (ymapsPromise) return ymapsPromise;
  ymapsPromise = new Promise((resolve, reject) => {
    if (typeof window === 'undefined') return reject(new Error('No window'));
    if (window.ymaps) return window.ymaps.ready(() => resolve(window.ymaps));
    const apiKey = process.env.NEXT_PUBLIC_YANDEX_MAPS_KEY;
    const params = new URLSearchParams({ lang: 'ru_RU' });
    if (apiKey) params.set('apikey', apiKey);
    const s = document.createElement('script');
    s.src = `https://api-maps.yandex.ru/2.1/?${params.toString()}`;
    s.async = true;
    s.onload = () => window.ymaps.ready(() => resolve(window.ymaps));
    s.onerror = reject;
    document.head.appendChild(s);
  });
  return ymapsPromise;
}
