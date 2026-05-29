export const metadata = {
  title: 'Политика конфиденциальности — АптекаА',
  description: 'Условия обработки персональных данных пользователей сайта aptekaa.ru.',
  alternates: { canonical: 'https://aptekaa.ru/politika-konfidencialnosti' },
};

import Link from 'next/link';

export default function Privacy() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-5 md:py-10 prose prose-slate">
      <nav className="text-xs text-slate-500 mb-4">
        <Link href="/" className="hover:text-emerald-700 no-underline">Главная</Link>
        <span className="mx-1.5">/</span><span>Политика конфиденциальности</span>
      </nav>
      <h1 className="text-3xl font-bold text-slate-900 mb-2">Политика конфиденциальности</h1>
      <p className="text-sm text-slate-500 mb-6">Редакция от января 2025 г.</p>

      <div className="space-y-5 text-slate-700 leading-relaxed">
        <section>
          <h2 className="text-xl font-bold text-slate-900 mb-2">1. Общие положения</h2>
          <p>Настоящая Политика определяет порядок обработки персональных данных пользователей сайта АптекаА в соответствии с Федеральным законом от 27.07.2006 №152-ФЗ «О персональных данных».</p>
        </section>
        <section>
          <h2 className="text-xl font-bold text-slate-900 mb-2">2. Оператор персональных данных</h2>
          <p>Общество с ограниченной ответственностью «Идеал-Фарм» (ООО «Идеал-Фарм»).<br />ИНН 5050110424 · КПП 505001001 · ОГРН 1145050001942.<br />Юридический адрес: 141195, Московская область, г. Фрязино, ул. Садовая, д. 1, помещ. II встроенное, этаж 1.<br />E-mail для обращений: info@aptekaa.ru</p>
        </section>
        <section>
          <h2 className="text-xl font-bold text-slate-900 mb-2">3. Состав обрабатываемых данных</h2>
          <p>Сайт собирает обезличенные данные посетителей (cookies, данные системы веб-аналитики), а также контактные данные, добровольно указываемые в формах связи (имя, телефон, e-mail).</p>
        </section>
        <section>
          <h2 className="text-xl font-bold text-slate-900 mb-2">4. Цели обработки</h2>
          <ul className="list-disc list-inside space-y-1">
            <li>Предоставление информации о наличии и ценах лекарственных препаратов</li>
            <li>Ответ на обращения пользователей</li>
            <li>Подключение аптек-партнёров</li>
            <li>Анализ посещаемости сайта и улучшение сервиса</li>
          </ul>
        </section>
        <section>
          <h2 className="text-xl font-bold text-slate-900 mb-2">5. Место хранения</h2>
          <p>Базы данных с персональной информацией граждан Российской Федерации находятся на территории Российской Федерации в соответствии с ч. 5 ст. 18 ФЗ №152-ФЗ.</p>
        </section>
        <section>
          <h2 className="text-xl font-bold text-slate-900 mb-2">6. Права субъекта ПД</h2>
          <p>Пользователь вправе в любой момент отозвать согласие, запросить удаление или изменение своих данных, направив обращение на e-mail: info@aptekaa.ru.</p>
        </section>
      </div>
    </div>
  );
}
