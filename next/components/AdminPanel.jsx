'use client';
import { useState, useEffect, useCallback } from 'react';
import { Star, Check, X, Trash2, LogOut } from 'lucide-react';

const TOKEN_KEY = 'aptekaa_admin_jwt';

function Stars({ value }) {
  const v = Math.round(value || 0);
  return (
    <span className="inline-flex">
      {[1, 2, 3, 4, 5].map((i) => (
        <Star key={i} className={`w-4 h-4 ${i <= v ? 'fill-amber-400 text-amber-400' : 'fill-slate-200 text-slate-200'}`} />
      ))}
    </span>
  );
}

export default function AdminPanel() {
  const [token, setToken] = useState(null);
  const [booted, setBooted] = useState(false);
  // login form
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loginErr, setLoginErr] = useState('');
  const [loggingIn, setLoggingIn] = useState(false);
  // queue
  const [tab, setTab] = useState('hold'); // hold | published
  const [items, setItems] = useState([]);
  const [pending, setPending] = useState(0);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(null); // id, действие в процессе

  useEffect(() => {
    try { setToken(sessionStorage.getItem(TOKEN_KEY)); } catch {}
    setBooted(true);
  }, []);

  const logout = useCallback(() => {
    try { sessionStorage.removeItem(TOKEN_KEY); } catch {}
    setToken(null); setItems([]);
  }, []);

  const load = useCallback(async (tk, status) => {
    if (!tk) return;
    setLoading(true); setErr('');
    try {
      const res = await fetch(`/api/admin/reviews?status=${status}&limit=200`, {
        headers: { Authorization: `Bearer ${tk}` },
      });
      if (res.status === 401 || res.status === 403) { logout(); setErr('Сессия истекла, войдите снова.'); return; }
      const j = await res.json();
      setItems(j.items || []);
      setPending(j.pending || 0);
    } catch { setErr('Не удалось загрузить отзывы.'); }
    setLoading(false);
  }, [logout]);

  useEffect(() => { if (token) load(token, tab); }, [token, tab, load]);

  const doLogin = async (e) => {
    e.preventDefault();
    setLoggingIn(true); setLoginErr('');
    try {
      const res = await fetch('/api/admin/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) {
        let m = 'Неверный логин или пароль';
        try { const j = await res.json(); if (j && j.detail) m = j.detail; } catch {}
        throw new Error(m);
      }
      const j = await res.json();
      try { sessionStorage.setItem(TOKEN_KEY, j.token); } catch {}
      setToken(j.token); setPassword('');
    } catch (e2) { setLoginErr(e2.message || 'Ошибка входа'); }
    setLoggingIn(false);
  };

  const act = async (id, action) => {
    setBusy(id + action);
    try {
      const res = await fetch(`/api/admin/reviews/${id}/${action}`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401 || res.status === 403) { logout(); return; }
      if (res.ok) setItems((prev) => prev.filter((r) => r.id !== id));
      if (action === 'approve' || action === 'reject') setPending((p) => Math.max(0, p - 1));
    } catch {}
    setBusy(null);
  };

  if (!booted) return null;

  // ---- Экран логина ----
  if (!token) {
    return (
      <div className="min-h-[70vh] flex items-center justify-center px-4">
        <form onSubmit={doLogin} className="w-full max-w-sm bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
          <h1 className="text-xl font-bold text-slate-900 mb-1">Вход в админ-панель</h1>
          <p className="text-sm text-slate-500 mb-5">Модерация отзывов</p>
          <label className="block text-sm font-medium text-slate-700 mb-1">Логин</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username"
            className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm mb-3 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 outline-none" />
          <label className="block text-sm font-medium text-slate-700 mb-1">Пароль</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password"
            className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm mb-4 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 outline-none" />
          {loginErr && <p className="text-sm text-red-600 mb-3">{loginErr}</p>}
          <button type="submit" disabled={loggingIn || !username || !password}
            className="w-full rounded-xl bg-emerald-600 px-4 py-3 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50">
            {loggingIn ? 'Входим…' : 'Войти'}
          </button>
        </form>
      </div>
    );
  }

  // ---- Дашборд ----
  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-xl font-bold text-slate-900">Модерация отзывов</h1>
        <button onClick={logout} className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800">
          <LogOut className="w-4 h-4" /> Выйти
        </button>
      </div>

      <div className="flex gap-2 mb-4">
        {[['hold', `На проверке${pending ? ` (${pending})` : ''}`], ['published', 'Опубликованные']].map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-3.5 py-2 rounded-xl text-sm font-medium border transition ${tab === k ? 'bg-emerald-50 border-emerald-400 text-emerald-700' : 'bg-white border-slate-300 text-slate-600 hover:border-slate-400'}`}>
            {label}
          </button>
        ))}
      </div>

      {err && <p className="text-sm text-red-600 mb-3">{err}</p>}
      {loading ? (
        <p className="text-sm text-slate-500">Загрузка…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-slate-500">{tab === 'hold' ? 'Очередь пуста — нет отзывов на проверке.' : 'Нет опубликованных отзывов.'}</p>
      ) : (
        <ul className="space-y-3">
          {items.map((r) => (
            <li key={r.id} className="bg-white border border-slate-200 rounded-xl p-4">
              <div className="flex items-center justify-between gap-3 mb-1">
                <Stars value={r.rating} />
                <time className="text-xs text-slate-400">{r.created_at ? new Date(r.created_at).toLocaleString('ru-RU') : ''}</time>
              </div>
              <a href={`/msk/preparaty/${r.slug}`} target="_blank" rel="noreferrer" className="text-xs text-emerald-700 underline break-all">{r.slug}</a>
              <p className="mt-2 text-sm text-slate-700 whitespace-pre-line">{r.text}</p>
              {Array.isArray(r.photos) && r.photos.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {r.photos.map((src, i) => (
                    <a key={i} href={src} target="_blank" rel="noreferrer" className="w-24 h-24 rounded-lg overflow-hidden border border-slate-200">
                      <img src={src} alt="" className="w-full h-full object-cover" />
                    </a>
                  ))}
                </div>
              )}
              <div className="mt-3 flex gap-2">
                {tab === 'hold' && (
                  <button onClick={() => act(r.id, 'approve')} disabled={busy === r.id + 'approve'}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50">
                    <Check className="w-4 h-4" /> Одобрить
                  </button>
                )}
                <button onClick={() => act(r.id, tab === 'hold' ? 'reject' : 'delete')} disabled={busy === r.id + (tab === 'hold' ? 'reject' : 'delete')}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-red-300 bg-white px-3 py-1.5 text-sm font-semibold text-red-600 hover:bg-red-50 disabled:opacity-50">
                  {tab === 'hold' ? <><X className="w-4 h-4" /> Отклонить</> : <><Trash2 className="w-4 h-4" /> Удалить</>}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
