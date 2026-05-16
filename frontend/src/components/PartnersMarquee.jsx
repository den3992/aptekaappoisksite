import React from 'react';

const PARTNERS = [
  'Ригла', '36,6', 'Здоровье', 'Горздрав', 'Столички', 'Будь Здоров',
  'Самсон-Фарма', 'Аптеки А5', 'Ноль Боли', 'Доктор Столетов',
  'Wer.ru', 'Планета Здоровья', 'Первая помощь', 'Озерки',
  'Радуга', 'Невис', 'ГосАптека', 'Лекарь',
];

function initials(name) {
  return name.replace(/[^а-яёa-z0-9]/gi, '').slice(0, 2).toUpperCase();
}

function Item({ name }) {
  return (
    <div className="group shrink-0 flex items-center gap-2.5 whitespace-nowrap cursor-default px-4">
      <div className="w-7 h-7 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center text-[10px] font-bold text-slate-400 shrink-0 group-hover:bg-emerald-50 group-hover:border-emerald-200 group-hover:text-emerald-600 transition-colors">
        {initials(name)}
      </div>
      <span className="text-[13px] font-semibold text-slate-600 group-hover:text-emerald-600 transition-colors">
        {name}
      </span>
      <span className="text-slate-200 text-base select-none ml-2">·</span>
    </div>
  );
}

export default function PartnersMarquee() {
  const list = [...PARTNERS, ...PARTNERS];
  return (
    <section className="relative py-8 md:py-10">

      <div className="max-w-7xl mx-auto px-4 mb-5 flex items-center justify-between">
        <h2 className="font-extrabold text-slate-900 text-xl md:text-2xl tracking-tight" style={{ fontFamily: "'Manrope', sans-serif" }}>
          Наши партнёры
        </h2>
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-50 border border-emerald-100 text-xs font-semibold text-emerald-700">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
          {PARTNERS.length}+ аптечных сетей
        </span>
      </div>

      <div className="overflow-hidden">
        <div className="marquee-container relative">
          <div className="marquee-track">
            {list.map((p, i) => <Item key={i} name={p} />)}
          </div>
          <div className="pointer-events-none absolute inset-y-0 left-0 w-20 z-10" style={{background:'linear-gradient(to right, rgba(240,253,244,0.7), transparent)'}} />
          <div className="pointer-events-none absolute inset-y-0 right-0 w-20 z-10" style={{background:'linear-gradient(to left, rgba(240,253,244,0.7), transparent)'}} />
        </div>
      </div>
    </section>
  );
}
