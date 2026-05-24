import React from 'react';
import Link from 'next/link';

export default function Consent() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-5 md:py-10">
      <nav className="text-xs text-slate-500 mb-4">
        <Link href="/" className="hover:text-emerald-700">Главная</Link>
        <span className="mx-1.5">/</span><span>Согласие на обработку ПД</span>
      </nav>
      <h1 className="text-3xl font-bold text-slate-900 mb-2">Согласие на обработку персональных данных</h1>
      <p className="text-sm text-slate-500 mb-6">Документ подготовлен в соответствии с ФЗ №152-ФЗ</p>

      <div className="space-y-5 text-slate-700 leading-relaxed">
        <p>Настоящим я, действуя свободно, своей волей и в своём интересе, даю своё согласие ООО «Идеал-Фарм» (ИНН 5050110424, ОГРН 1145050001942, юр. адрес: 141195, Московская обл., г. Фрязино, ул. Садовая, д. 1, помещ. II, далее — Оператор) на обработку моих персональных данных.</p>
        <h2 className="text-xl font-bold text-slate-900">Перечень персональных данных</h2>
        <ul className="list-disc list-inside space-y-1">
          <li>Фамилия, имя, отчество</li>
          <li>Контактный телефон</li>
          <li>Адрес электронной почты</li>
          <li>Город</li>
        </ul>
        <h2 className="text-xl font-bold text-slate-900">Цели обработки</h2>
        <p>Предоставление информационных услуг, ответ на обращения, рассылка новостей и полезных материалов, подключение аптек-партнёров.</p>
        <h2 className="text-xl font-bold text-slate-900">Действия с ПД</h2>
        <p>Сбор, запись, систематизация, накопление, хранение, уточнение (обновление, изменение), извлечение, использование, передача (распространение, предоставление, доступ), обезличивание, блокирование, удаление, уничтожение.</p>
        <h2 className="text-xl font-bold text-slate-900">Срок согласия</h2>
        <p>Согласие действует бессрочно и может быть отозвано путём направления письменного уведомления на e-mail: info@aptekaa.ru.</p>
      </div>
    </div>
  );
}
