// Yandex Maps JS API v3 loader.
// ymaps3 has native pinch-to-zoom — cluster markers don't intercept touch events.

let ymaps3Promise = null;

export function loadYmaps() {
  if (ymaps3Promise) return ymaps3Promise;
  ymaps3Promise = new Promise((resolve, reject) => {
    if (typeof window === 'undefined') return reject(new Error('No window'));
    if (window.ymaps3) return window.ymaps3.ready.then(() => resolve(window.ymaps3));
    const apiKey = process.env.REACT_APP_YANDEX_MAPS_KEY;
    const params = new URLSearchParams({ lang: 'ru_RU' });
    if (apiKey) params.set('apikey', apiKey);
    const s = document.createElement('script');
    s.src = `https://api-maps.yandex.ru/v3/?${params.toString()}`;
    s.async = true;
    s.onload = () => window.ymaps3.ready.then(() => resolve(window.ymaps3));
    s.onerror = reject;
    document.head.appendChild(s);
  });
  return ymaps3Promise;
}
