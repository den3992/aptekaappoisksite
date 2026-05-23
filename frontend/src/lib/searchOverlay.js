// Открытие SearchOverlay с обходом iOS-блокировки клавиатуры.
//
// На iOS Safari клавиатура открывается только если input.focus() вызван
// СИНХРОННО внутри пользовательского жеста. SearchOverlay монтируется
// асинхронно (CustomEvent → React render), и к моменту появления реального
// input'а user-gesture уже истекает. Решение: фокусируем временный
// невидимый input ПРЯМО СЕЙЧАС (это разблокирует клавиатуру), потом
// перекидываем фокус на реальный input — iOS воспринимает это как смену
// фокуса при уже открытой клавиатуре и оставляет её видимой.
//
// Используется обоими местами входа в overlay: иконкой «Поиск» в нижнем
// таб-баре и кнопкой-строкой поиска на мобильной главной.

export function openSearchOverlay() {
  const tmp = document.createElement('input');
  tmp.setAttribute('type', 'text');
  tmp.setAttribute('inputmode', 'search');
  tmp.setAttribute('lang', 'ru');
  // font-size: 16px чтобы Safari не зумил viewport.
  tmp.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;font-size:16px;border:0;padding:0;z-index:-1;';
  document.body.appendChild(tmp);
  tmp.focus();

  window.dispatchEvent(new CustomEvent('search-overlay:open'));

  const transfer = (attempt = 0) => {
    const real = document.querySelector('[data-testid="search-overlay-input"]');
    if (real) {
      real.focus();
      tmp.remove();
    } else if (attempt < 20) {
      requestAnimationFrame(() => transfer(attempt + 1));
    } else {
      tmp.remove();
    }
  };
  requestAnimationFrame(() => transfer(0));
}
