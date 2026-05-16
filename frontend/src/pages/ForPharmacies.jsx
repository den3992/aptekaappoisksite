import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Mail, FileSpreadsheet, Server, ShieldCheck, ArrowRight, CheckCircle2, Send } from 'lucide-react';
import axios from 'axios';
import { useToast } from '../hooks/use-toast';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function ForPharmacies() {
  const { toast } = useToast();
  const [form, setForm] = useState({ chain: '', city: '', email: '', phone: '', count: '', comment: '' });
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const onChange = (k) => (e) => setForm(s => ({ ...s, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.email || !form.chain) {
      toast({ title: 'Заполните обязательные поля', description: 'Название и e-mail' });
      return;
    }
    setSubmitting(true);
    try {
      await axios.post(`${API}/partner-requests`, form, { timeout: 15000 });
      setDone(true);
      setForm({ chain: '', city: '', email: '', phone: '', count: '', comment: '' });
    } catch (err) {
      toast({ title: 'Ошибка отправки', description: err?.response?.data?.detail?.[0]?.msg || 'Попробуйте ещё раз' });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <section className="bg-gradient-to-b from-emerald-50/60 to-white border-b border-slate-100">
        <div className="max-w-5xl mx-auto px-4 pt-5 pb-8 md:pt-12 md:pb-12">
          <nav className="text-xs text-slate-500 mb-4">
            <Link to="/" className="hover:text-emerald-700">Главная</Link>
            <span className="mx-1.5">/</span><span>Для аптек</span>
          </nav>
          <div className="inline-flex items-center gap-2 bg-white border border-emerald-100 rounded-full px-3 py-1 mb-5 text-xs text-emerald-800">
            <ShieldCheck className="w-3.5 h-3.5" /> Подключение бесплатное
          </div>
          <h1 className="text-3xl md:text-5xl font-extrabold tracking-tight text-slate-900">Подключите аптеку<br /><span className="text-emerald-600">к сервису АптекаА бесплатно</span></h1>
          <p className="mt-5 text-lg text-slate-600 max-w-3xl">
            Привлекайте новых клиентов из яндекс-поиска. Наш сервис отображает ваши цены и остатки в карточках препаратов, когда люди ищут лекарство в вашем городе.
          </p>
        </div>
      </section>

      <section className="max-w-5xl mx-auto px-4 py-8 md:py-12">
        <h2 className="text-2xl font-bold text-slate-900 mb-6">Как это работает</h2>
        <div className="grid md:grid-cols-3 gap-4">
          {[
            { i: '01', icon: Send, title: 'Оставьте заявку', desc: 'Напишите нам или заполните форму ниже — мы свяжемся и обсудим детали' },
            { i: '02', icon: Server, title: 'Лёгкая выгрузка', desc: 'Предоставим отдельный FTP-доступ для выгрузки. Поможем с настройкой из вашей учётной системы.' },
            { i: '03', icon: FileSpreadsheet, title: 'Выгрузка прайс-листа', desc: 'Аптека регулярно отправляет файл с остатками и ценами — мы обрабатываем и показываем их на сайте' },
          ].map(s => (
            <div key={s.i} className="bg-white border border-slate-100 rounded-xl p-6">
              <div className="flex items-center justify-between mb-4">
                <div className="w-10 h-10 rounded-lg bg-emerald-50 text-emerald-700 flex items-center justify-center"><s.icon className="w-5 h-5" /></div>
                <div className="text-3xl font-extrabold text-emerald-100">{s.i}</div>
              </div>
              <h3 className="font-semibold text-slate-900 mb-1">{s.title}</h3>
              <p className="text-sm text-slate-600 leading-relaxed">{s.desc}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="max-w-5xl mx-auto px-4 pb-8 md:pb-12">
        <div className="bg-slate-50 border border-slate-100 rounded-2xl p-8">
          <h2 className="text-2xl font-bold text-slate-900 mb-3">Что мы предоставляем</h2>
          <ul className="space-y-3 text-slate-700">
            {[
              'Поможем настроить автоматическую выгрузку прайс-листа из вашей информационной системы',
              'Поддерживаем любые форматы прайс-листов',
              'Отдельный FTP-доступ',
              'Аптеки обновляют данные ежедневно',
              'Карточка вашей аптеки на сайте с полным ассортиментом, контактами и отображением на карте',
              'Аналитика посещаемости ваших карточек в личном кабинете',
            ].map(t => (
              <li key={t} className="flex items-start gap-2.5"><CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" /><span>{t}</span></li>
            ))}
          </ul>
        </div>
      </section>

      <section className="max-w-5xl mx-auto px-4 pb-10 md:pb-16">
        <div className="bg-white border border-slate-100 rounded-2xl p-6 md:p-8">
          <div className="grid md:grid-cols-[1fr_auto] gap-6 items-start mb-6">
            <div>
              <h2 className="text-2xl font-bold text-slate-900 mb-2">Подключение к сервису</h2>
              <p className="text-slate-600">Оставьте контакты — мы свяжемся и поможем с настройкой выгрузки.</p>
            </div>
            <a href="mailto:partner@aptekaa.ru" className="inline-flex items-center gap-2 text-emerald-700 font-medium hover:underline">
              <Mail className="w-4 h-4" /> partner@aptekaa.ru
            </a>
            <div className="mt-2 text-sm text-slate-600">
              Подключены и есть техвопрос? Пишите на{' '}
              <a href="mailto:support@aptekaa.ru" className="text-emerald-700 font-medium hover:underline">support@aptekaa.ru</a>
            </div>
          </div>
          <form onSubmit={submit} className="grid md:grid-cols-2 gap-4" data-testid="partner-request-form">
            {done && (
              <div className="md:col-span-2 bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3 text-sm text-emerald-800 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4" /> Заявка отправлена! Мы свяжемся с вами в ближайшее время.
              </div>
            )}
            <Field label="Название аптеки / сети*" name="chain" testId="partner-chain-input" value={form.chain} onChange={onChange('chain')} placeholder="ООО «Аптека»" />
            <Field label="Город" name="city" testId="partner-city-input" value={form.city} onChange={onChange('city')} placeholder="Москва" />
            <Field label="E-mail*" name="email" testId="partner-email-input" type="email" value={form.email} onChange={onChange('email')} placeholder="manager@apteka.ru" />
            <Field label="Телефон" name="phone" testId="partner-phone-input" value={form.phone} onChange={onChange('phone')} placeholder="+7 (___) ___-__-__" />
            <Field label="Количество точек" name="count" testId="partner-count-input" value={form.count} onChange={onChange('count')} placeholder="5" />
            <Field label="Учётная система" name="comment" testId="partner-comment-input" value={form.comment} onChange={onChange('comment')} placeholder="1С, M-Аптека…" />
            <div className="md:col-span-2 flex items-center justify-between gap-3 pt-2">
              <p className="text-xs text-slate-500">Нажимая «Отправить», вы соглашаетесь с <Link to="/soglasie-na-obrabotku-pd" className="underline">обработкой перс. данных</Link></p>
              <button type="submit" disabled={submitting} data-testid="partner-request-submit" className="inline-flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white font-medium px-6 py-3 rounded-lg transition">
                {submitting ? 'Отправляем…' : 'Отправить'} <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </form>
        </div>
      </section>
    </div>
  );
}

function Field({ label, value, onChange, placeholder, type = 'text', testId, name }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-slate-600 mb-1.5">{label}</span>
      <input
        name={name}
        type={type}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        data-testid={testId}
        className="w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-base md:text-sm outline-none focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
      />
    </label>
  );
}
