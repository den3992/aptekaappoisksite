// Kill-switch service worker.
//
// Phase 9: после миграции CRA → Next.js (Phase 8 cutover) браузеры юзеров,
// которые посещали сайт до миграции, имеют зарегистрированный workbox-SW
// из старой CRA-сборки. Этот SW кешит /index.html и /static/* которые
// больше не существуют — пользователи могут видеть устаревший интерфейс
// несколько дней (пока сами не обновят страницу с Ctrl+Shift+R).
//
// Когда браузер запрашивает /service-worker.js для обновления старого SW,
// он получает ЭТУ версию: она снимает регистрацию + чистит все caches +
// перезагружает все открытые табы.
//
// После того как все активные юзеры один раз получат kill-switch (несколько
// недель), этот файл можно удалить.

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', async () => {
  try {
    const cacheNames = await caches.keys();
    await Promise.all(cacheNames.map(n => caches.delete(n)));
    await self.registration.unregister();
    const clients = await self.clients.matchAll({ type: 'window' });
    clients.forEach(c => {
      try { c.navigate(c.url); } catch (e) { /* cross-origin guard */ }
    });
  } catch (e) {
    // best-effort cleanup; не критично если что-то упадёт
  }
});
