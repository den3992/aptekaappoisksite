'use client';
import { useState, useEffect } from 'react';
import Link from 'next/link';
import { X, Send } from 'lucide-react';

const MESSENGER_OPTIONS = [
  { id: 'max', label: 'Max' },
  { id: 'whatsapp', label: 'WhatsApp' },
  { id: 'telegram', label: 'Telegram' },
];

// Модалка «Заявка на поиск лекарства». Используется на странице препарата
// (с привязкой medication/slug) и на главной (общая заявка, без препарата).
export default function LeadModal({ open, onClose, medication, slug, city }) {
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [phone, setPhone] = useState('');
  const [messengers, setMessengers] = useState([]);
  const [consent, setConsent] = useState(false);
  const [website, setWebsite] = useState(''); // honeypot
  const [status, setStatus] = useState('idle'); // idle | sending | done | error
  const [errMsg, setErrMsg] = useState('');

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = prevOverflow; };
  }, [open, onClose]);

  // Сброс на любую смену open: при открытии — свежая форма (в т.ч. после
  // гонки «закрыли во время отправки»), при закрытии — не держим ПД в памяти.
  useEffect(() => {
    setName(''); setAddress(''); setPhone(''); setMessengers([]);
    setConsent(false); setWebsite(''); setStatus('idle'); setErrMsg('');
  }, [open]);

  if (!open) return null;

  const toggleMsg = (id) =>
    setMessengers((prev) => prev.includes(id) ? prev.filter((m) => m !== id) : [...prev, id]);

  const canSubmit = name.trim().length >= 2 && address.trim().length >= 3
    && phone.replace(/\D/g, '').length >= 5 && consent && status !== 'sending';

  const submit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setStatus('sending'); setErrMsg('');
    try {
      const res = await fetch('/api/search-request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name, address, phone, messengers, consent, website,
          medication: medication || null, slug: slug || null, city: city || null,
        }),
      });
      if (!res.ok) {
        let m = 'Не удалось отправить заявку. Попробуйте позже.';
        try { const j = await res.json(); if (j && j.detail) m = j.detail; } catch {}
        throw new Error(m);
      }
      setStatus('done');
    } catch (err) {
      setStatus('error');
      setErrMsg(err.message || 'Ошибка отправки');
    }
  };

  return (
    <div
      className="fixed inset-0 z-[80] flex items-end sm:items-center justify-center bg-black/50 p-0 sm:p-4"
      onClick={onClose}
      data-testid="lead-modal"
    >
      <div
        className="bg-white w-full sm:max-w-md rounded-t-2xl sm:rounded-2xl shadow-xl max-h-[92vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Заявка на поиск лекарства"
      >
        <div className="flex items-start justify-between p-5 pb-3 border-b border-slate-100">
          <div className="min-w-0">
            <h3 className="text-lg font-bold text-slate-900 leading-tight">Заявка на поиск лекарства</h3>
            {medication && <p className="text-sm text-slate-500 mt-0.5 truncate">{medication}</p>}
          </div>
          <button onClick={onClose} aria-label="Закрыть" className="shrink-0 -mr-1 -mt-1 p-2 text-slate-400 hover:text-slate-700">
            <X className="w-5 h-5" />
          </button>
        </div>

        {status === 'done' ? (
          <div className="p-6 text-center" data-testid="lead-success">
            <div className="w-12 h-12 mx-auto rounded-full bg-emerald-50 border border-emerald-200 flex items-center justify-center">
              <Send className="w-6 h-6 text-emerald-600" />
            </div>
            <p className="mt-3 text-base font-semibold text-slate-900">Заявка отправлена!</p>
            <p className="mt-1 text-sm text-slate-600">
              Мы найдём препарат в ближайшей к вам аптеке и свяжемся с вами по телефону{messengers.length ? ' или в мессенджере' : ''}.
            </p>
            <button onClick={onClose} className="mt-5 w-full rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-700">
              Готово
            </button>
          </div>
        ) : (
          <form onSubmit={submit} className="p-5 space-y-3.5">
            <p className="text-sm text-slate-600">
              Оставьте контакты — найдём лекарство в ближайшей к вам аптеке и сообщим, где оно есть.
            </p>
            {/* honeypot — скрыт от людей */}
            <input
              type="text" value={website} onChange={(e) => setWebsite(e.target.value)}
              name="website" tabIndex={-1} autoComplete="off"
              className="hidden" aria-hidden="true"
            />
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Имя</label>
              <input
                type="text" value={name} onChange={(e) => setName(e.target.value)}
                required maxLength={120} placeholder="Как к вам обращаться"
                className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Адрес</label>
              <input
                type="text" value={address} onChange={(e) => setAddress(e.target.value)}
                required maxLength={300} placeholder="Город, улица, дом — чтобы найти аптеку рядом"
                className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Телефон</label>
              <input
                type="tel" value={phone} onChange={(e) => setPhone(e.target.value)}
                required maxLength={40} placeholder="+7 ___ ___-__-__"
                className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 outline-none"
              />
            </div>
            <div>
              <span className="block text-sm font-medium text-slate-700 mb-1.5">Где с вами удобнее связаться?</span>
              <div className="flex flex-wrap gap-2">
                {MESSENGER_OPTIONS.map((opt) => {
                  const on = messengers.includes(opt.id);
                  return (
                    <button
                      type="button" key={opt.id} onClick={() => toggleMsg(opt.id)}
                      data-testid={`lead-msg-${opt.id}`}
                      className={`px-3.5 py-2 rounded-xl text-sm font-medium border transition-colors ${on ? 'bg-emerald-50 border-emerald-400 text-emerald-700' : 'bg-white border-slate-300 text-slate-600 hover:border-slate-400'}`}
                    >
                      {on ? '✓ ' : ''}{opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
            <label className="flex items-start gap-2.5 cursor-pointer pt-0.5">
              <input
                type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)}
                className="mt-0.5 w-4 h-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
              />
              <span className="text-xs text-slate-500 leading-snug">
                Я согласен на обработку персональных данных в соответствии с{' '}
                <Link href="/soglasie-na-obrabotku-pd" target="_blank" className="text-emerald-700 underline">политикой обработки ПД</Link>.
                Данные используются только для связи по этой заявке и не передаются третьим лицам.
              </span>
            </label>
            {status === 'error' && (
              <p className="text-sm text-red-600" data-testid="lead-error">{errMsg}</p>
            )}
            <button
              type="submit" disabled={!canSubmit}
              data-testid="lead-submit-btn"
              className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 py-3 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {status === 'sending' ? 'Отправляем…' : <>Отправить заявку <Send className="w-4 h-4" /></>}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
