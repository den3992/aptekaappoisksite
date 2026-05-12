import React from 'react';
import { Link } from 'react-router-dom';
import { Pill, Phone, Mail, ShieldCheck } from 'lucide-react';
import PillIcon from './PillIcon';

export default function Footer() {
  return (
    <footer className="bg-slate-50 border-t border-slate-100 mt-12">
      <div className="max-w-7xl mx-auto px-4 py-10">
        {/* warning band */}
        <div className="flex items-start gap-3 p-4 mb-8 bg-amber-50 border border-amber-200 rounded-lg">
          <ShieldCheck className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
          <p className="text-sm text-amber-900 leading-relaxed">
            <strong>Имеются противопоказания. Необходима консультация со специалистом.</strong>{' '}
            Сведения о ценах и наличии лекарственных препаратов предоставляются аптеками-партнёрами и носят справочный характер. Не является публичной офертой.
          </p>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
          <div className="col-span-2">
            <Link to="/" className="flex flex-col items-start mb-3 leading-none">
              <div className="flex items-center gap-2 md:gap-2.5">
                <PillIcon className="w-4 h-4 md:w-5 md:h-5" />
                <span className="text-lg font-extrabold text-slate-900 tracking-tight" style={{ fontFamily: "'Manrope', sans-serif" }}>Аптека<span className="text-emerald-600">А</span></span>
              </div>
              <span className="text-[13px] text-slate-500 mt-1.5">Актуальное наличие лекарств</span>
            </Link>
            <p className="text-sm text-slate-600 leading-relaxed max-w-md">
              Информационный сервис по поиску лекарств, бадов и медицинских изделий в аптеках России. Не продаём и не бронируем препараты.
            </p>
            <div className="mt-4 space-y-1.5 text-sm text-slate-700">
              <div className="flex items-center gap-2"><Phone className="w-4 h-4 text-emerald-600" /> 8 (800) 700-70-70</div>
              <div className="flex items-center gap-2"><Mail className="w-4 h-4 text-emerald-600" /> info@aptekaa.ru</div>
            </div>
          </div>

          <div>
            <h4 className="font-semibold text-slate-900 mb-3">Сервис</h4>
            <ul className="space-y-2 text-sm text-slate-600">
              <li><Link to="/o-servise" className="hover:text-emerald-700">О сервисе</Link></li>
              <li><Link to="/dlya-aptek" className="hover:text-emerald-700">Для аптек</Link></li>
              <li><Link to="/kontakty" className="hover:text-emerald-700">Контакты</Link></li>
              <li><Link to="/apteki" className="hover:text-emerald-700">Аптеки</Link></li>
            </ul>
          </div>

          <div>
            <h4 className="font-semibold text-slate-900 mb-3">Документы</h4>
            <ul className="space-y-2 text-sm text-slate-600">
              <li><Link to="/politika-konfidencialnosti" className="hover:text-emerald-700">Политика конфиденциальности</Link></li>
              <li><Link to="/soglasie-na-obrabotku-pd" className="hover:text-emerald-700">Согласие на обработку ПД</Link></li>
              <li><Link to="/preparaty" className="hover:text-emerald-700">Каталог препаратов</Link></li>
              <li><Link to="/kategorii" className="hover:text-emerald-700">Все категории</Link></li>
            </ul>
          </div>
        </div>

        <div className="mt-10 pt-6 border-t border-slate-200 flex flex-col md:flex-row md:items-center md:justify-between gap-3 text-xs text-slate-500">
          <div>© {new Date().getFullYear()} АптекаА · ООО «Идеал-Фарм» · ИНН 5050110424. Все права защищены.</div>
          <div>Сервис соответствует требованиям ФЗ №152 «О персональных данных». 18+</div>
        </div>
      </div>
    </footer>
  );
}
