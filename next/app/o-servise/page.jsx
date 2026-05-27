export const metadata = {
  title: 'О сервисе АптекаА — кто мы и зачем сделали аптечную справочную',
  description: 'АптекаА — бесплатный аптечный агрегатор по Москве и СПб. Кто мы, как работаем, почему не продаём лекарства.',
  alternates: { canonical: 'https://aptekaa.ru/o-servise' },
};

import React from 'react';
import { aboutPageJsonLd } from '../../lib/schemas';
import Link from 'next/link';
import { ShieldCheck, Heart, Search, Clock, Building2 } from 'lucide-react';

export default function About() {
  const graph = aboutPageJsonLd();
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(graph) }} />
    <div className="max-w-4xl mx-auto px-4 py-5 md:py-10">
      <nav className="text-xs text-slate-500 mb-4">
        <Link href="/" className="hover:text-emerald-700">Главная</Link>
        <span className="mx-1.5">/</span><span>О сервисе</span>
      </nav>
      <h1 className="text-2xl sm:text-3xl md:text-4xl font-bold text-slate-900 mb-3 leading-tight">О сервисе АптекаА</h1>
      <p className="text-slate-600 leading-relaxed mb-6 md:mb-8 text-sm md:text-base">
        АптекаА — информационный сервис по поиску лекарственных препаратов, биологически активных добавок и медицинских изделий в аптеках России. Мы помогаем людям быстро находить нужные препараты по лучшей цене и в ближайших аптеках.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-8 md:mb-10">
        {[
          { i: Search, t: 'Быстрый поиск', d: 'Находите препарат в десятках аптек за секунды' },
          { i: Heart, t: 'Забота о здоровье', d: 'Все данные проверяются и обновляются' },
          { i: ShieldCheck, t: 'Соответствие законодательству РФ', d: 'ФЗ №152, хранение данных в России' },
          { i: Clock, t: 'Актуальные данные', d: 'Ежедневное обновление информации о наличии' },
        ].map((f, i) => (
          <div key={i} className="bg-white border border-slate-100 rounded-xl p-5 flex gap-4">
            <div className="w-10 h-10 rounded-lg bg-emerald-50 text-emerald-700 flex items-center justify-center shrink-0"><f.i className="w-5 h-5" /></div>
            <div><h3 className="font-semibold text-slate-900">{f.t}</h3><p className="text-sm text-slate-600 mt-1 leading-relaxed">{f.d}</p></div>
          </div>
        ))}
      </div>

      <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 text-sm text-amber-900 leading-relaxed">
        <p><strong>Важно:</strong> АптекаА не является аптекой и не осуществляет продажу и бронирование лекарств. Сведения о ценах и наличии носят справочный характер. Имеются противопоказания, необходима консультация со специалистом.</p>
      </div>
    </div>
    </>
  );
}
