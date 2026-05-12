import React from 'react';
import { Building2 } from 'lucide-react';

// 18 pharmacy chains as marquee partners
const PARTNERS = [
  'Ригла', '36,6', 'Здоровье', 'Горздрав', 'Столички', 'Будь Здоров',
  'Самсон-Фарма', 'Аптеки А5', 'Ноль Боли', 'Доктор Столетов',
  'Wer.ru', 'Планета Здоровья', 'Первая помощь', 'Озерки',
  'Радуга', 'Невис', 'ГосАптека', 'Лекарь',
];

function Item({ name }) {
  return (
    <div className="shrink-0 mx-3 flex items-center gap-2 px-5 py-3 bg-white border border-slate-100 rounded-xl shadow-sm">
      <div className="w-8 h-8 rounded-lg bg-emerald-50 text-emerald-700 flex items-center justify-center">
        <Building2 className="w-4 h-4" />
      </div>
      <span className="text-sm font-semibold text-slate-700 whitespace-nowrap">{name}</span>
    </div>
  );
}

export default function PartnersMarquee() {
  // Duplicate the array for seamless loop
  const list = [...PARTNERS, ...PARTNERS];
  return (
    <section className="relative bg-slate-50 border-y border-slate-100 py-10 overflow-hidden">
      <div className="max-w-7xl mx-auto px-4 mb-5 flex items-baseline justify-between">
        <div>
          <h2 className="text-2xl md:text-3xl font-bold text-slate-900">Наши партнёры</h2>
          <p className="text-slate-500 text-sm mt-1">Цены и наличие из аптечных сетей по всей России</p>
        </div>
        <div className="text-sm text-slate-500 hidden sm:block">{PARTNERS.length}+ сетей</div>
      </div>

      <div className="marquee-container relative">
        <div className="marquee-track">
          {list.map((p, i) => <Item key={i} name={p} />)}
        </div>
        {/* edge fades */}
        <div className="pointer-events-none absolute inset-y-0 left-0 w-24 bg-gradient-to-r from-slate-50 to-transparent" />
        <div className="pointer-events-none absolute inset-y-0 right-0 w-24 bg-gradient-to-l from-slate-50 to-transparent" />
      </div>
    </section>
  );
}
