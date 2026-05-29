'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Search, X, Pill } from 'lucide-react';
import { useCity } from '../context/CityContext';
import { suggestMeds } from '../api/client';
import { dedupeMeds, formatName, formatManufacturer } from '../utils/text';

/**
 * Full-screen mobile search overlay.
 *
 * Opens via a CustomEvent `search-overlay:open` (dispatched by MobileTabBar).
 * Provides a focused, modal-style search experience:
 *   - Auto-focus input → opens keyboard
 *   - Body scroll locked, rest of site dimmed
 *   - Up to 50 suggestions, vertically scrollable
 *   - Scrolling the suggestions list blurs the input (closes keyboard)
 *   - Submitting (Найти) blurs the input and navigates to /poisk full-results
 */
export default function SearchOverlay() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const { city } = useCity();
  const router = useRouter();
  const inputRef = useRef(null);

  // Open via custom event from MobileTabBar (or anywhere).
  useEffect(() => {
    const handler = () => setOpen(true);
    window.addEventListener('search-overlay:open', handler);
    return () => window.removeEventListener('search-overlay:open', handler);
  }, []);

  // Lock body scroll + focus input when overlay opens.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const t = setTimeout(() => inputRef.current?.focus(), 60);
    return () => {
      document.body.style.overflow = prev;
      clearTimeout(t);
    };
  }, [open]);

  // Close on Escape (desktop) and Android back-button handled by history.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Debounced suggestions (up to 50 items, scrollable list).
  useEffect(() => {
    if (!open) { setSuggestions([]); return; }
    if (!q.trim() || q.trim().length < 2) { setSuggestions([]); return; }
    let cancelled = false;
    const t = setTimeout(() => {
      suggestMeds(q.trim(), 50)
        .then((d) => { if (!cancelled) setSuggestions(d || []); })
        .catch(() => {});
    }, 150);
    return () => { cancelled = true; clearTimeout(t); };
  }, [q, open]);

  const close = () => {
    setOpen(false);
    setQ('');
    setSuggestions([]);
  };

  const onSubmit = (e) => {
    e?.preventDefault();
    const term = q.trim();
    if (!term) return;
    inputRef.current?.blur();              // close keyboard
    router.push(`/${city.id}/poisk?q=${encodeURIComponent(term)}`);
    close();
  };

  // Closing keyboard when user starts scrolling the suggestions list.
  const onListScroll = () => {
    if (inputRef.current && document.activeElement === inputRef.current) {
      inputRef.current.blur();
    }
  };

  if (!open) return null;

  const items = dedupeMeds(suggestions);

  return (
    <div
      className="md:hidden fixed inset-0 z-[100] flex flex-col"
      data-testid="search-overlay"
      role="dialog"
      aria-modal="true"
    >
      {/* Dim backdrop — covers the whole screen behind the sheet */}
      <div
        className="absolute inset-0 bg-slate-900/55 backdrop-blur-[1.5px]"
        onClick={close}
        data-testid="search-overlay-backdrop"
      />

      {/* Search bar (above dim) */}
      <div className="relative bg-white pt-[env(safe-area-inset-top)] px-2 pb-2 border-b border-slate-100 shadow-sm">
        <form onSubmit={onSubmit} className="flex items-center gap-1.5 mt-2">
          <button
            type="button"
            onClick={close}
            className="w-10 h-10 inline-flex items-center justify-center text-slate-600 active:text-slate-900 shrink-0"
            data-testid="search-overlay-close"
            aria-label="Закрыть поиск"
          >
            <X className="w-5 h-5" />
          </button>
          <div className="flex-1 min-w-0 flex items-center border border-emerald-400 rounded-lg bg-white shadow-sm">
            <Search className="w-4 h-4 text-rose-500 ml-3" />
            <input
              ref={inputRef}
              type="text"
              inputMode="search" lang="ru"
              autoComplete="off"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Найдите препарат в аптеках"
              aria-label="Поиск препарата"
              className="flex-1 min-w-0 px-3 py-3 text-base bg-transparent outline-none"
              data-testid="search-overlay-input"
            />
            {q && (
              <button
                type="button"
                onClick={() => { setQ(''); inputRef.current?.focus(); }}
                className="px-2 text-slate-400 active:text-slate-700"
                data-testid="search-overlay-clear"
                aria-label="Очистить поле"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
          <button
            type="submit"
            data-testid="search-overlay-submit"
            className="px-3 h-10 text-sm font-medium text-white bg-emerald-600 rounded-md active:bg-emerald-700 shrink-0"
          >
            Найти
          </button>
        </form>
      </div>

      {/* Suggestions panel — white area with up to 50 scrollable items */}
      <div
        onScroll={onListScroll}
        className="relative flex-1 bg-white overflow-y-auto overscroll-contain"
        data-testid="search-overlay-suggestions"
        style={{ WebkitOverflowScrolling: 'touch' }}
      >
        {items.map((s) => (
          <Link
            key={s.slug}
            href={`/${city.id}/preparaty/${s.slug}`}
            className="flex items-center gap-3 px-4 py-3 active:bg-emerald-50 transition border-b border-slate-100"
            onClick={close}
            data-testid="search-overlay-suggestion-item"
          >
            <Pill className="w-4 h-4 text-emerald-600 shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-slate-900 truncate">{formatName(s.name)}</div>
              <div className="text-xs text-slate-500 truncate">
                {[formatName(s.form), s.dosage, formatManufacturer(s.manufacturer)].filter(Boolean).join(' · ')}
              </div>
            </div>
          </Link>
        ))}
        {q.trim().length >= 2 && items.length === 0 && (
          <div className="p-8 text-center text-sm text-slate-500" data-testid="search-overlay-empty">
            Ничего не найдено по запросу «{q.trim()}»
          </div>
        )}
        {q.trim().length < 2 && (
          <div className="p-8 text-center text-sm text-slate-400" data-testid="search-overlay-hint">
            Начните вводить название препарата
          </div>
        )}
      </div>
    </div>
  );
}
