import React, { useEffect, useRef } from 'react';

const PARTNERS = [
  { name: 'Ригла',            logo: 'rigla.png' },
  { name: '36,6',             logo: '366.png' },
  { name: 'Здоровье',         logo: null },
  { name: 'Горздрав',         logo: 'gorzdrav.png' },
  { name: 'Столички',         logo: 'stolichki.png' },
  { name: 'Будь Здоров',      logo: 'budzdorov.png' },
  { name: 'Самсон-Фарма',     logo: 'samson-pharma.png' },
  { name: 'Аптеки А5',        logo: null },
  { name: 'Ноль Боли',        logo: '0boli.png' },
  { name: 'Доктор Столетов',  logo: 'drstoletov.png' },
  { name: 'Wer.ru',           logo: 'wer.svg' },
  { name: 'Планета Здоровья', logo: 'planetazdorovo.png' },
  { name: 'Первая помощь',    logo: 'pervaya-pomosh.png' },
  { name: 'Озерки',           logo: 'ozerki.png' },
  { name: 'Радуга',           logo: 'raduga.png' },
  { name: 'Невис',            logo: 'nevis.png' },
  { name: 'ГосАптека',        logo: null },
  { name: 'Лекарь',           logo: null },
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
            // Если файл по какой-то причине не загрузился — заменяем
            // изображение на текстовый квадратик с инициалами.
            const el = e.currentTarget;
            const fallback = document.createElement('div');
            fallback.className = 'w-10 h-10 md:w-7 md:h-7 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center text-[15px] md:text-[10px] font-bold text-slate-400 shrink-0';
            fallback.textContent = initials(name);
            el.replaceWith(fallback);
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
  // Тройной список: средняя копия всегда внутри viewport, не пересекает
  // границы overflow:hidden — устраняет iOS Safari баг с tile-rendering
  // на краях клиппинг-региона.
  const list = [...PARTNERS, ...PARTNERS, ...PARTNERS];
  const trackRef = useRef(null);

  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;
    const apply = () => {
      const cycle = track.scrollWidth / 3;
      const speed = window.innerWidth < 640 ? 50 : 40; // px/s
      track.style.setProperty('--marquee-cycle', cycle + 'px');
      track.style.animationDuration = (cycle / speed) + 's';
    };
    apply();
    window.addEventListener('resize', apply);
    return () => window.removeEventListener('resize', apply);
  }, []);

  return (
    <section className="relative py-12 md:py-10">
      <div className="max-w-7xl mx-auto px-4 mb-7 md:mb-5 flex items-center justify-between">
        <h2 className="font-extrabold text-slate-900 text-xl md:text-2xl tracking-tight" style={{ fontFamily: "'Manrope', sans-serif" }}>
          Наши партнёры
        </h2>
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-50 border border-emerald-100 text-xs font-semibold text-emerald-700">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
          {PARTNERS.length}+ аптечных сетей
        </span>
      </div>

      <div className="overflow-hidden marquee-host">
        <div ref={trackRef} className="marquee-track-v2 flex items-center">
          {list.map((p, i) => <Item key={i} name={p.name} logo={p.logo} />)}
        </div>
      </div>
    </section>
  );
}
