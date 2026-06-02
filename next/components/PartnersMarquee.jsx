'use client';
import { useEffect, useRef } from 'react';
// Только сети, цены которых мы реально агрегируем (есть данные в prices_real).
// Не показываем «партнёров», которых у нас нет — это вводило бы в заблуждение.
const PARTNERS = [
  { name: 'Горздрав',    logo: 'gorzdrav.png' },     // msk, spb
  { name: 'Аптека 36,6', logo: '366.png' },          // msk, spb
  { name: 'Ригла',       logo: 'rigla.png' },         // msk
  { name: 'Максавит',    logo: 'maksavit.png' },      // msk, spb, krd, nn
  { name: 'Аптечество',  logo: 'aptechestvo.png' },   // nn
];

function initials(name) {
  return name.replace(/[^а-яёa-z0-9]/gi, '').slice(0, 2).toUpperCase();
}

function Item({ name, logo }) {
  return (
    <div className="group shrink-0 flex items-center gap-4 md:gap-2.5 whitespace-nowrap cursor-default px-6 md:px-4">
      {logo ? (
        <img
          src={"/img/partners/" + logo}
          alt={name}
          loading="lazy"
          className="w-10 h-10 md:w-7 md:h-7 rounded-lg object-contain bg-white border border-slate-200 shrink-0 p-0.5"
          onError={(e) => {
            const el = e.currentTarget;
            const fb = document.createElement('div');
            fb.className = 'w-10 h-10 md:w-7 md:h-7 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center text-[15px] md:text-[10px] font-bold text-slate-400 shrink-0';
            fb.textContent = initials(name);
            el.replaceWith(fb);
          }}
        />
      ) : (
        <div className="w-10 h-10 md:w-7 md:h-7 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center text-[15px] md:text-[10px] font-bold text-slate-400 shrink-0 group-hover:bg-emerald-50 group-hover:border-emerald-200 group-hover:text-emerald-600 transition-colors">
          {initials(name)}
        </div>
      )}
      <span className="text-[19px] md:text-[13px] font-semibold text-slate-600 group-hover:text-emerald-600 transition-colors">
        {name}
      </span>
      <span className="text-slate-200 text-2xl md:text-base select-none ml-3 md:ml-2">·</span>
    </div>
  );
}

export default function PartnersMarquee() {
  // Тройной список — обеспечивает бесшовный loop при телепорте scrollLeft
  const list = [...PARTNERS, ...PARTNERS, ...PARTNERS];
  const hostRef = useRef(null);
  const pausedRef = useRef(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    // Скорость в пикселях за секунду
    const SPEED = 50;
    let last = performance.now();
    let raf = 0;
    let pos = 0;
    let started = false;
    let prevCw = 0;
    let stableTicks = 0;

    const cycle = () => host.scrollWidth / 3;

    const tick = (now) => {
      const dt = Math.min(50, now - last) / 1000;
      last = now;
      const cw = cycle();

      // Ждём пока scrollWidth перестанет меняться (картинки догрузились).
      // Только после этого стартуем — иначе будут "скачки" из-за safety-checks
      // при росте cw в первые секунды после загрузки.
      if (!started) {
        if (cw > 0 && Math.abs(cw - prevCw) < 1) stableTicks++;
        else stableTicks = 0;
        prevCw = cw;
        if (stableTicks >= 5 && cw > 0) {
          pos = cw;
          host.scrollLeft = Math.round(pos);
          started = true;
        }
        raf = requestAnimationFrame(tick);
        return;
      }

      if (cw > 0) {
        if (pausedRef.current) {
          pos = host.scrollLeft;
        } else {
          pos += SPEED * dt;
          if (pos >= cw * 2) pos -= cw;
          else if (pos < cw * 0.5) pos += cw;
          const target = Math.round(pos);
          if (host.scrollLeft !== target) host.scrollLeft = target;
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    // Pause при touch/mouseenter; resume при отпускании/уходе
    const onPauseStart = () => { pausedRef.current = true; };
    const onPauseEnd = () => { pausedRef.current = false; };
    host.addEventListener('touchstart', onPauseStart, { passive: true });
    host.addEventListener('touchend',   onPauseEnd,   { passive: true });
    host.addEventListener('touchcancel',onPauseEnd,   { passive: true });
    host.addEventListener('mouseenter', onPauseStart);
    host.addEventListener('mouseleave', onPauseEnd);
    const onResize = () => { /* cycle() пересчитается на следующем tick */ };
    window.addEventListener('resize', onResize);

    return () => {
      cancelAnimationFrame(raf);
      host.removeEventListener('touchstart', onPauseStart);
      host.removeEventListener('touchend',   onPauseEnd);
      host.removeEventListener('touchcancel',onPauseEnd);
      host.removeEventListener('mouseenter', onPauseStart);
      host.removeEventListener('mouseleave', onPauseEnd);
      window.removeEventListener('resize', onResize);
    };
  }, []);

  return (
    <section className="relative py-12 md:py-10">
      <div className="max-w-7xl mx-auto px-4 mb-7 md:mb-5 flex items-center justify-between">
        <h2 className="font-extrabold text-slate-900 text-xl md:text-2xl tracking-tight" style={{ fontFamily: "'Manrope', sans-serif" }}>
          Наши партнёры
        </h2>
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-50 border border-emerald-100 text-xs font-semibold text-emerald-700">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
          {PARTNERS.length} аптечных сетей
        </span>
      </div>

      <div
        ref={hostRef}
        className="marquee-native overflow-x-auto no-scrollbar"
      >
        <div className="flex items-center w-max">
          {list.map((p, i) => <Item key={i} name={p.name} logo={p.logo} />)}
        </div>
      </div>
    </section>
  );
}
