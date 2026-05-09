// Centralized Yandex Maps JS API loader.
// Reads the API key from REACT_APP_YANDEX_MAPS_KEY and loads the script once.

let ymapsPromise = null;

export function loadYmaps() {
  if (ymapsPromise) return ymapsPromise;
  ymapsPromise = new Promise((resolve, reject) => {
    if (typeof window === 'undefined') return reject(new Error('No window'));
    if (window.ymaps) return window.ymaps.ready(() => resolve(window.ymaps));
    const apiKey = process.env.REACT_APP_YANDEX_MAPS_KEY;
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
