import React from 'react';
import { Link } from 'react-router-dom';
import { Mail, Phone, MapPin, Clock, Briefcase } from 'lucide-react';

export default function Contacts() {
  return (
    <div className="max-w-4xl mx-auto px-4 py-10">
      <nav className="text-xs text-slate-500 mb-4">
        <Link to="/" className="hover:text-emerald-700">Главная</Link>
        <span className="mx-1.5">/</span><span>Контакты</span>
      </nav>
      <h1 className="text-3xl md:text-4xl font-bold text-slate-900 mb-3">Контакты</h1>
      <p className="text-slate-600 mb-8">Отвечаем в рабочие дни с 9:00 до 18:00 до МСК</p>

      <div className="grid sm:grid-cols-2 gap-3 mb-8">
        {[
          { i: Phone, t: 'Горячая линия', v: '8 (800) 700-70-70', s: 'Бесплатно по РФ' },
          { i: Mail, t: 'Общая почта', v: 'info@lekarstva.rf', s: 'Для любых вопросов' },
          { i: Briefcase, t: 'Для аптек-партнёров', v: 'partners@lekarstva.rf', s: 'Подключение и настройка' },
        ].map((c, i) => (
          <div key={i} className="bg-white border border-slate-100 rounded-xl p-5">
            <div className="flex items-center gap-3 mb-2">
              <div className="w-9 h-9 rounded-lg bg-emerald-50 text-emerald-700 flex items-center justify-center"><c.i className="w-4 h-4" /></div>
              <h3 className="font-semibold text-slate-900">{c.t}</h3>
            </div>
            <div className="text-lg font-semibold text-slate-800">{c.v}</div>
            <div className="text-xs text-slate-500 mt-0.5">{c.s}</div>
          </div>
        ))}
      </div>

      <div className="bg-slate-50 border border-slate-100 rounded-xl p-6 text-sm text-slate-600 leading-relaxed">
        <h2 className="text-base font-semibold text-slate-900 mb-2">Реквизиты</h2>
        <p>ООО «Лекарства.РФ»<br />ИНН 7700000000 · ОГРН 1234567890123</p>
      </div>
    </div>
  );
}
