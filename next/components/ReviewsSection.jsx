'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import { Star, X, Send } from 'lucide-react';

// Блок отзывов на странице препарата.
// - Полный блок (заголовок, рейтинг, распределение, список, schema) — только
//   при наличии опубликованных отзывов (count>=1). На пустых препаратах —
//   лишь компактная кнопка «Оставить отзыв» (затравка), без тонкого текста.
// - Отзывы — на канонический препарат (slug), общие для всех городов.
// - Никнейм не собираем: показываем только дату и оценку.

const RU_DATE = (iso) => {
  try {
    return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(iso));
  } catch { return ''; }
};

function Stars({ value, size = 16 }) {
  // value — число 1..5 (для дробного показываем округление до целого).
  const v = Math.round(value || 0);
  return (
    <span className="inline-flex items-center" aria-label={`Оценка ${value} из 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <Star
          key={i}
          width={size}
          height={size}
          className={i <= v ? 'fill-amber-400 text-amber-400' : 'fill-slate-200 text-slate-200'}
        />
      ))}
    </span>
  );
}

function ReviewModal({ open, onClose, slug, onPublished }) {
  const [rating, setRating] = useState(0);
  const [hover, setHover] = useState(0);
  const [text, setText] = useState('');
  const [consent, setConsent] = useState(false);
  const [website, setWebsite] = useState(''); // honeypot
  const [status, setStatus] = useState('idle'); // idle|sending|done|error
  const [doneKind, setDoneKind] = useState('published'); // published|hold
  const [errMsg, setErrMsg] = useState('');
  const [photos, setPhotos] = useState([]); // File[]
  const [previews, setPreviews] = useState([]); // object URLs
  const tsRef = useRef(0);

  const MAX_PHOTOS = 3;

  // Сжимаем фото в браузере ДО отправки: ресайз ≤1280px → JPEG q0.82.
  // Так аплоад с телефона занимает килобайты, а не мегабайты (фикс «Load Failed»
  // на медленном мобильном). Любой декодируемый браузером формат (вкл. HEIC на
  // iOS) превращается в компактный JPEG. На сервере фото ещё раз пережимается в
  // WebP. Если декод не удался — отправляем оригинал (сервер обработает).
  const downscale = async (file) => {
    try {
      const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
      const max = 1280;
      const scale = Math.min(1, max / Math.max(bmp.width, bmp.height));
      const w = Math.max(1, Math.round(bmp.width * scale));
      const h = Math.max(1, Math.round(bmp.height * scale));
      const canvas = document.createElement('canvas');
      canvas.width = w; canvas.height = h;
      canvas.getContext('2d').drawImage(bmp, 0, 0, w, h);
      if (bmp.close) bmp.close();
      const blob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', 0.82));
      if (!blob) return file;
      const base = (file.name || 'photo').replace(/\.[^.]+$/, '');
      return new File([blob], base + '.jpg', { type: 'image/jpeg' });
    } catch {
      return file;
    }
  };

  const addPhotos = async (fileList) => {
    const incoming = Array.from(fileList || []);
    if (!incoming.length) return;
    const slots = MAX_PHOTOS - photos.length;
    const processed = await Promise.all(incoming.slice(0, Math.max(0, slots)).map(downscale));
    setPhotos((prev) => {
      const merged = [...prev, ...processed].slice(0, MAX_PHOTOS);
      setPreviews((old) => { old.forEach((u) => URL.revokeObjectURL(u)); return merged.map((f) => URL.createObjectURL(f)); });
      return merged;
    });
  };
  const removePhoto = (idx) => {
    setPhotos((prev) => {
      const next = prev.filter((_, i) => i !== idx);
      setPreviews((old) => { old.forEach((u) => URL.revokeObjectURL(u)); return next.map((f) => URL.createObjectURL(f)); });
      return next;
    });
  };

  useEffect(() => {
    if (!open) return;
    tsRef.current = Date.now();
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = prev; };
  }, [open, onClose]);

  useEffect(() => {
    // Сброс при каждом открытии/закрытии.
    setRating(0); setHover(0); setText(''); setConsent(false);
    setWebsite(''); setStatus('idle'); setErrMsg(''); setDoneKind('published');
    setPreviews((old) => { old.forEach((u) => URL.revokeObjectURL(u)); return []; });
    setPhotos([]);
  }, [open]);

  if (!open) return null;

  const canSubmit = rating >= 1 && rating <= 5 && text.trim().length >= 20 && consent && status !== 'sending';

  const submit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setStatus('sending'); setErrMsg('');
    try {
      const fd = new FormData();
      fd.append('slug', slug);
      fd.append('rating', String(rating));
      fd.append('text', text.trim());
      fd.append('consent', 'true');
      fd.append('website', website);
      fd.append('ts', String(tsRef.current));
      photos.forEach((f) => fd.append('photos', f, f.name));
      // Content-Type не ставим — браузер сам выставит multipart boundary.
      const res = await fetch('/api/reviews', { method: 'POST', body: fd });
      if (!res.ok) {
        let m = 'Не удалось отправить отзыв. Попробуйте позже.';
        try { const j = await res.json(); if (j && j.detail) m = j.detail; } catch {}
        throw new Error(m);
      }
      const j = await res.json().catch(() => ({}));
      setDoneKind(j.status === 'hold' ? 'hold' : 'published');
      setStatus('done');
      if (j.status !== 'hold') {
        onPublished && onPublished({ id: j.id || Math.random().toString(36).slice(2), rating, text: text.trim(), created_at: new Date().toISOString() });
      }
    } catch (err) {
      setStatus('error');
      setErrMsg(err.message || 'Ошибка отправки');
    }
  };

  return (
    <div
      className="fixed inset-0 z-[80] flex items-end sm:items-center justify-center bg-black/50 p-0 sm:p-4"
      onClick={onClose}
      data-testid="review-modal"
    >
      <div
        className="bg-white w-full sm:max-w-md rounded-t-2xl sm:rounded-2xl shadow-xl max-h-[92vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        role="dialog" aria-modal="true" aria-label="Оставить отзыв о препарате"
      >
        <div className="flex items-start justify-between p-5 pb-3 border-b border-slate-100">
          <h3 className="text-lg font-bold text-slate-900 leading-tight">Ваш отзыв о препарате</h3>
          <button onClick={onClose} aria-label="Закрыть" className="shrink-0 -mr-1 -mt-1 p-2 text-slate-400 hover:text-slate-700">
            <X className="w-5 h-5" />
          </button>
        </div>

        {status === 'done' ? (
          <div className="p-6 text-center" data-testid="review-success">
            <div className="w-12 h-12 mx-auto rounded-full bg-emerald-50 border border-emerald-200 flex items-center justify-center">
              <Send className="w-6 h-6 text-emerald-600" />
            </div>
            <p className="mt-3 text-base font-semibold text-slate-900">Спасибо за отзыв!</p>
            <p className="mt-1 text-sm text-slate-600">
              {doneKind === 'hold'
                ? 'Отзыв отправлен и появится на странице после проверки.'
                : 'Ваш отзыв опубликован на странице препарата.'}
            </p>
            <button onClick={onClose} className="mt-5 w-full rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-700">
              Готово
            </button>
          </div>
        ) : (
          <form onSubmit={submit} className="p-5 space-y-3.5">
            {/* honeypot */}
            <input type="text" value={website} onChange={(e) => setWebsite(e.target.value)}
              name="website" tabIndex={-1} autoComplete="off" className="hidden" aria-hidden="true" />

            <div>
              <span className="block text-sm font-medium text-slate-700 mb-1.5">Ваша оценка</span>
              <div className="flex items-center gap-1" data-testid="review-stars-input">
                {[1, 2, 3, 4, 5].map((i) => (
                  <button
                    type="button" key={i}
                    onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(0)}
                    onClick={() => setRating(i)}
                    aria-label={`${i} из 5`}
                    className="p-0.5"
                  >
                    <Star className={`w-7 h-7 transition ${i <= (hover || rating) ? 'fill-amber-400 text-amber-400' : 'fill-slate-200 text-slate-200'}`} />
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Отзыв</label>
              <textarea
                value={text} onChange={(e) => setText(e.target.value)}
                rows={4} maxLength={2000} minLength={20}
                placeholder="Поделитесь опытом применения: помог ли препарат, удобство приёма, побочные эффекты…"
                data-testid="review-text-input"
                className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 outline-none resize-y"
              />
              <p className="mt-1 text-xs text-slate-400">{text.trim().length}/20 минимум. Без ссылок и контактов.</p>
            </div>

            <div>
              <span className="block text-sm font-medium text-slate-700 mb-1.5">Фото (необязательно, до {MAX_PHOTOS})</span>
              <div className="flex flex-wrap items-center gap-2">
                {previews.map((src, i) => (
                  <div key={i} className="relative w-16 h-16 rounded-lg overflow-hidden border border-slate-200">
                    <img src={src} alt="" className="w-full h-full object-cover" />
                    <button type="button" onClick={() => removePhoto(i)} aria-label="Убрать фото"
                      className="absolute top-0.5 right-0.5 w-5 h-5 rounded-full bg-black/55 text-white flex items-center justify-center">
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                ))}
                {photos.length < MAX_PHOTOS && (
                  <label className="w-16 h-16 rounded-lg border border-dashed border-slate-300 flex items-center justify-center text-2xl text-slate-400 cursor-pointer hover:border-emerald-400 hover:text-emerald-500">
                    +
                    <input type="file" accept="image/*" multiple className="hidden"
                      data-testid="review-photo-input"
                      onChange={(e) => { addPhotos(e.target.files); e.target.value = ''; }} />
                  </label>
                )}
              </div>
              {photos.length > 0 && (
                <p className="mt-1 text-xs text-amber-600">Отзыв с фото публикуется после проверки модератором.</p>
              )}
            </div>

            <label className="flex items-start gap-2.5 cursor-pointer pt-0.5">
              <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)}
                className="mt-0.5 w-4 h-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500" />
              <span className="text-xs text-slate-500 leading-snug">
                Я согласен на публикацию отзыва и обработку данных в соответствии с{' '}
                <Link href="/soglasie-na-obrabotku-pd" target="_blank" className="text-emerald-700 underline">политикой</Link>.
                Отзыв отражает личное мнение и не является медицинской рекомендацией.
              </span>
            </label>

            {status === 'error' && (
              <p className="text-sm text-red-600" data-testid="review-error">{errMsg}</p>
            )}

            <button
              type="submit" disabled={!canSubmit}
              data-testid="review-submit-btn"
              className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 py-3 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {status === 'sending' ? 'Отправляем…' : <>Опубликовать отзыв <Send className="w-4 h-4" /></>}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

export default function ReviewsSection({ slug, initialReviews }) {
  const init = initialReviews && initialReviews.count >= 1 ? initialReviews : null;
  const [count, setCount] = useState(init ? init.count : 0);
  const [avg, setAvg] = useState(init ? init.avg : 0);
  const [dist, setDist] = useState(init ? init.dist : null);
  const [items, setItems] = useState(init ? init.items : []);
  const [hasMore, setHasMore] = useState(init ? init.count > init.items.length : false);
  const [apiPage, setApiPage] = useState(0); // 0 = ещё не грузили через API
  const [loadingMore, setLoadingMore] = useState(false);
  const [open, setOpen] = useState(false);
  const [lightbox, setLightbox] = useState(null); // URL увеличенного фото

  const loadMore = useCallback(async () => {
    if (loadingMore) return;
    setLoadingMore(true);
    try {
      const next = apiPage > 0 ? apiPage + 1 : 1;
      const res = await fetch(`/api/reviews/${encodeURIComponent(slug)}?page=${next}&page_size=10`);
      const j = await res.json();
      setCount(j.count); setAvg(j.avg); setDist(j.dist);
      // page=1 — свежие 10 (надмножество SSR-пятёрки) → заменяем; дальше — добавляем.
      setItems((prev) => (next === 1 ? j.items : [...prev, ...j.items]));
      setApiPage(next);
      setHasMore(j.has_more);
    } catch { /* ignore */ }
    setLoadingMore(false);
  }, [slug, apiPage, loadingMore]);

  const onPublished = useCallback((rev) => {
    // Оптимистично добавляем свой отзыв в начало списка.
    setItems((prev) => [rev, ...prev]);
    setCount((c) => {
      const nc = c + 1;
      setAvg((a) => Math.round(((a * c + rev.rating) / nc) * 10) / 10);
      return nc;
    });
    setDist((d) => {
      if (!d) return d;
      const nd = { ...d };
      nd[String(rev.rating)] = (nd[String(rev.rating)] || 0) + 1;
      return nd;
    });
  }, []);

  const hasReviews = count >= 1;

  return (
    <section className="mb-8 md:mb-12" data-testid="reviews-section">
      {hasReviews ? (
        <>
          <div className="flex items-center justify-between gap-3 mb-4">
            <h2 className="text-xl md:text-2xl font-bold text-slate-900 leading-tight">Отзывы</h2>
            <button
              onClick={() => setOpen(true)}
              data-testid="review-open-btn"
              className="shrink-0 inline-flex items-center gap-1.5 rounded-xl border border-emerald-300 bg-white px-3.5 py-2 text-sm font-semibold text-emerald-700 hover:bg-emerald-50 transition"
            >
              Оставить отзыв
            </button>
          </div>

          <div className="bg-white border border-slate-200 rounded-xl p-4 md:p-5">
            {/* Сводка: средняя оценка + распределение */}
            <div className="flex flex-col sm:flex-row sm:items-center gap-4 pb-4 border-b border-slate-100">
              <div className="flex items-center gap-3">
                <div className="text-4xl font-extrabold text-slate-900 leading-none" data-testid="reviews-avg">
                  {avg.toString().replace('.', ',')}
                </div>
                <div>
                  <Stars value={avg} size={18} />
                  <div className="text-xs text-slate-500 mt-1" data-testid="reviews-count">
                    {count} {pluralReviews(count)}
                  </div>
                </div>
              </div>
              {dist && (
                <div className="flex-1 sm:max-w-xs space-y-1">
                  {[5, 4, 3, 2, 1].map((s) => {
                    const n = dist[String(s)] || 0;
                    const pct = count ? Math.round((n / count) * 100) : 0;
                    return (
                      <div key={s} className="flex items-center gap-2 text-xs text-slate-500">
                        <span className="w-3 tabular-nums">{s}</span>
                        <Star className="w-3 h-3 fill-amber-400 text-amber-400 shrink-0" />
                        <span className="flex-1 h-1.5 rounded-full bg-slate-100 overflow-hidden">
                          <span className="block h-full bg-amber-400" style={{ width: `${pct}%` }} />
                        </span>
                        <span className="w-5 text-right tabular-nums">{n}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Список отзывов */}
            <ul className="divide-y divide-slate-100" data-testid="reviews-list">
              {items.map((r) => (
                <li key={r.id} className="py-4">
                  <div className="flex items-center justify-between gap-3">
                    <Stars value={r.rating} size={15} />
                    <time className="text-xs text-slate-400">{RU_DATE(r.created_at)}</time>
                  </div>
                  <p className="mt-2 text-sm text-slate-700 leading-relaxed whitespace-pre-line">{r.text}</p>
                  {Array.isArray(r.photos) && r.photos.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-2" data-testid="review-photos">
                      {r.photos.map((src, i) => (
                        <button key={i} type="button" onClick={() => setLightbox(src)}
                          className="w-20 h-20 rounded-lg overflow-hidden border border-slate-200 hover:opacity-90">
                          <img src={src} alt="Фото из отзыва" loading="lazy" className="w-full h-full object-cover" />
                        </button>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ul>

            {hasMore && (
              <button
                onClick={loadMore} disabled={loadingMore}
                data-testid="reviews-more-btn"
                className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-medium text-slate-600 hover:border-slate-300 disabled:opacity-50"
              >
                {loadingMore ? 'Загружаем…' : 'Показать ещё отзывы'}
              </button>
            )}
          </div>

          <p className="mt-3 text-xs text-slate-400 leading-snug">
            Отзывы отражают личное мнение посетителей и не являются медицинской рекомендацией.
            Перед применением ознакомьтесь с инструкцией и проконсультируйтесь с врачом.
          </p>
        </>
      ) : (
        // Пустое состояние — только компактная кнопка-затравка, без тонкого текста.
        <button
          onClick={() => setOpen(true)}
          data-testid="review-open-btn"
          className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-300 bg-white px-4 py-2.5 text-sm font-semibold text-emerald-700 hover:bg-emerald-50 transition"
        >
          Оставить отзыв о препарате
        </button>
      )}

      <ReviewModal open={open} onClose={() => setOpen(false)} slug={slug} onPublished={onPublished} />

      {lightbox && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/80 p-4" onClick={() => setLightbox(null)} data-testid="review-lightbox">
          <img src={lightbox} alt="Фото из отзыва" className="max-w-full max-h-full rounded-lg" />
          <button onClick={() => setLightbox(null)} aria-label="Закрыть" className="absolute top-4 right-4 p-2 text-white/80 hover:text-white">
            <X className="w-7 h-7" />
          </button>
        </div>
      )}
    </section>
  );
}

function pluralReviews(n) {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return 'отзывов';
  if (b > 1 && b < 5) return 'отзыва';
  if (b === 1) return 'отзыв';
  return 'отзывов';
}
