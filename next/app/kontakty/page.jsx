export const metadata = {
  title: 'Контакты АптекаА — email и реквизиты',
  description: 'АптекаА — почта info@aptekaa.ru для вопросов посетителей и подключения аптек-партнёров. Реквизиты сервиса.',
  alternates: { canonical: 'https://aptekaa.ru/kontakty' },
};

import Link from 'next/link';
import { Mail, Briefcase, LifeBuoy } from 'lucide-react';

export default function Contacts() {
  return (
    <div className="max-w-4xl mx-auto px-4 py-5 md:py-10">
      <nav className="text-xs text-slate-500 mb-4">
        <Link href="/" className="hover:text-emerald-700">Главная</Link>
        <span className="mx-1.5">/</span><span>Контакты</span>
      </nav>
      <h1 className="text-2xl sm:text-3xl md:text-4xl font-bold text-slate-900 mb-3">Контакты</h1>
      <p className="text-slate-600 mb-8">Отвечаем в рабочие дни с 9:00 до 18:00 МСК</p>

      <div className="grid sm:grid-cols-2 gap-3 mb-8">
        {[
          { i: Mail, t: 'Общая почта', v: 'info@aptekaa.ru', s: 'Для любых вопросов от посетителей сайта' },
          { i: Briefcase, t: 'Для аптек-партнёров', v: 'partner@aptekaa.ru', s: 'Подключение и настройка' },
          { i: LifeBuoy, t: 'Техподдержка для аптек', v: 'support@aptekaa.ru', s: 'Уже подключённым партнёрам' },
          { i: Mail, t: 'Загрузка прайс-листов', v: 'price@aptekaa.ru', s: 'Отправка XLSX/CSV прайсов' },
        ].map((c, i) => (
          <div key={i} className="bg-white border border-slate-100 rounded-xl p-5">
            <div className="flex items-center gap-3 mb-2">
              <div className="w-9 h-9 rounded-lg bg-emerald-50 text-emerald-700 flex items-center justify-center"><c.i className="w-4 h-4" /></div>
              <h3 className="font-semibold text-slate-900">{c.t}</h3>
            </div>
            <div className="text-base font-semibold text-slate-800 leading-snug">{c.v}</div>
            <div className="text-xs text-slate-500 mt-0.5">{c.s}</div>
          </div>
        ))}
      </div>

      {/* Полные юридические реквизиты — коммерческий фактор для Яндекса
          и подтверждение легальности информационного сервиса. */}
      <section className="bg-white border border-slate-100 rounded-xl p-5 md:p-6">
        <h2 className="text-lg font-bold text-slate-900 mb-4">Реквизиты</h2>
        <dl className="grid sm:grid-cols-2 gap-x-8 gap-y-2.5 text-sm">
          <div className="flex flex-col">
            <dt className="text-xs text-slate-500">Полное наименование</dt>
            <dd className="text-slate-800 font-medium">Индивидуальный предприниматель Егорова Анастасия Васильевна</dd>
          </div>
          <div className="flex flex-col">
            <dt className="text-xs text-slate-500">ИНН</dt>
            <dd className="text-slate-800 font-medium">—</dd>
          </div>
          <div className="flex flex-col">
            <dt className="text-xs text-slate-500">ОГРНИП</dt>
            <dd className="text-slate-800 font-medium">—</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
