import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import axios from 'axios';
import { CheckCircle2, XCircle, Copy, Loader2, Inbox, ShieldAlert, LogOut } from 'lucide-react';
import SEOHead from '../components/SEOHead';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const TOKEN_KEY = 'aptekaa_admin_jwt';

/**
 * Hidden admin page to review/approve partner requests.
 *
 * Auth flow:
 *  1. Login form (username + password) — POST /api/admin/login → JWT.
 *  2. JWT stored in sessionStorage; sent as Authorization: Bearer header.
 *  3. Expires in 8h (server-side); on 401/403 we clear storage + show form.
 *  4. Legacy ?token=<jwt> still accepted for direct deep-links (e.g. e-mail).
 */
export default function PartnerAdmin() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [token, setToken] = useState('');
  const [loginInput, setLoginInput] = useState('');
  const [passwordInput, setPasswordInput] = useState('');
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState('new');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState(null);
  const [issued, setIssued] = useState({});

  useEffect(() => {
    const urlTok = params.get('token');
    if (urlTok) {
      sessionStorage.setItem(TOKEN_KEY, urlTok);
      setToken(urlTok);
      navigate('/partner-admin', { replace: true });
      return;
    }
    const stored = sessionStorage.getItem(TOKEN_KEY);
    if (stored) setToken(stored);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const authHeaders = () => ({ Authorization: `Bearer ${token}` });

  const refresh = async () => {
    setLoading(true); setError('');
    try {
      const { data } = await axios.get(`${API}/admin/partner-requests`, {
        headers: authHeaders(),
        params: filter !== 'all' ? { status: filter } : {},
      });
      setItems(data);
    } catch (e) {
      const s = e?.response?.status;
      if (s === 401 || s === 403) {
        setError('Сессия истекла. Войдите снова.');
        sessionStorage.removeItem(TOKEN_KEY);
        setToken('');
      } else {
        setError('Ошибка загрузки');
      }
      setItems([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { if (token) refresh(); /* eslint-disable-next-line */ }, [token, filter]);

  const approve = async (rid) => {
    setBusyId(rid);
    try {
      const { data } = await axios.post(`${API}/admin/partner-requests/${rid}/approve`, null, {
        headers: authHeaders(),
      });
      setIssued(prev => ({ ...prev, [rid]: { token: data.token, pharmacy_id: data.pharmacy_id } }));
      await refresh();
    } catch (e) {
      alert('Ошибка одобрения');
    } finally {
      setBusyId(null);
    }
  };

  const reject = async (rid) => {
    if (!window.confirm('Отклонить заявку?')) return;
    setBusyId(rid);
    try {
      await axios.post(`${API}/admin/partner-requests/${rid}/reject`, null, {
        headers: authHeaders(),
      });
      await refresh();
    } catch (e) {
      alert('Ошибка отклонения');
    } finally {
      setBusyId(null);
    }
  };

  const logout = () => {
    sessionStorage.removeItem(TOKEN_KEY);
    setToken('');
    setItems([]);
    setError('');
  };

  const onLogin = async (e) => {
    e.preventDefault();
    setError('');
    if (!loginInput.trim() || !passwordInput) return;
    try {
      const { data } = await axios.post(`${API}/admin/login`, {
        username: loginInput.trim(),
        password: passwordInput,
      });
      sessionStorage.setItem(TOKEN_KEY, data.token);
      setToken(data.token);
      setLoginInput('');
      setPasswordInput('');
    } catch (e) {
      const s = e?.response?.status;
      if (s === 401) setError('Неверный логин или пароль');
      else if (s === 429) setError('Слишком много попыток. Подождите несколько минут.');
      else setError('Ошибка входа');
    }
  };

  const copy = (text) => navigator.clipboard.writeText(text);

  // ----- Login screen -----
  if (!token) {
    return (
      <div className="max-w-md mx-auto px-4 py-20">
        <SEOHead seo={{ title: 'Кабинет администратора | АптекаА' }} />
        <div className="text-center mb-6">
          <ShieldAlert className="w-10 h-10 text-emerald-600 mx-auto mb-3" />
          <h1 className="text-xl font-bold text-slate-900 mb-1">Кабинет администратора</h1>
          <p className="text-slate-500 text-sm">Войдите в систему.</p>
        </div>
        <form onSubmit={onLogin} className="space-y-3">
          <input
            type="text"
            value={loginInput}
            onChange={(e) => setLoginInput(e.target.value)}
            placeholder="Логин"
            autoComplete="username"
            autoFocus
            data-testid="admin-login-input"
            className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm outline-none focus:border-emerald-400"
          />
          <input
            type="password"
            value={passwordInput}
            onChange={(e) => setPasswordInput(e.target.value)}
            placeholder="Пароль"
            autoComplete="current-password"
            data-testid="admin-password-input"
            className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm outline-none focus:border-emerald-400"
          />
          <button
            type="submit"
            data-testid="admin-login-btn"
            className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-medium py-2.5 rounded-lg"
          >
            Войти
          </button>
          {error && (
            <div className="text-sm text-rose-600 text-center">{error}</div>
          )}
        </form>
      </div>
    );
  }

  // ----- Authenticated view -----
  return (
    <div className="max-w-6xl mx-auto px-4 py-8" data-testid="partner-admin-page">
      <SEOHead seo={{ title: 'Заявки партнёров | АптекаА' }} />
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-slate-900 mb-1">Заявки партнёров</h1>
          <p className="text-slate-500 text-sm">Скрытая страница администратора. Не индексируется.</p>
        </div>
        <button
          onClick={logout}
          data-testid="admin-logout-btn"
          className="inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-rose-600 px-3 py-1.5 rounded-lg border border-slate-200 hover:border-rose-300"
        >
          <LogOut className="w-3.5 h-3.5" /> Выйти
        </button>
      </div>

      <div className="flex gap-2 mb-6">
        {[
          { id: 'new', label: 'Новые' },
          { id: 'approved', label: 'Одобренные' },
          { id: 'rejected', label: 'Отклонённые' },
          { id: 'all', label: 'Все' },
        ].map(f => (
          <button key={f.id} onClick={() => setFilter(f.id)}
            className={`px-3 py-1.5 text-sm rounded-lg ${filter === f.id ? 'bg-emerald-600 text-white' : 'bg-white border border-slate-200 hover:border-emerald-400'}`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-rose-50 border border-rose-100 rounded-lg text-sm text-rose-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-center py-16 text-slate-500"><Loader2 className="w-6 h-6 mx-auto animate-spin" /></div>
      ) : items.length === 0 ? (
        <div className="bg-white border border-slate-100 rounded-xl px-6 py-12 text-center text-slate-500 text-sm">
          <Inbox className="w-8 h-8 mx-auto text-slate-300 mb-2" />
          Заявок нет
        </div>
      ) : (
        <div className="space-y-3">
          {items.map(r => {
            const newIssued = issued[r.id];
            return (
              <div key={r.id} data-testid="partner-request-row" className="bg-white border border-slate-100 rounded-xl p-5">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="font-semibold text-slate-900">{r.chain}</h3>
                      <span className={`text-[10px] uppercase font-semibold px-2 py-0.5 rounded ${
                        r.status === 'new' ? 'bg-blue-50 text-blue-700' :
                        r.status === 'approved' ? 'bg-emerald-50 text-emerald-700' :
                        'bg-slate-100 text-slate-600'
                      }`}>{r.status}</span>
                    </div>
                    <div className="grid sm:grid-cols-2 gap-x-6 gap-y-1 text-sm text-slate-700">
                      <div>📧 <a href={`mailto:${r.email}`} className="text-emerald-700 hover:underline">{r.email}</a></div>
                      {r.phone && <div>📞 {r.phone}</div>}
                      {r.city && <div>🏙 {r.city}</div>}
                      {r.count && <div>🏪 точек: {r.count}</div>}
                      {r.comment && <div className="sm:col-span-2 text-slate-500">💬 {r.comment}</div>}
                    </div>
                    <div className="text-[11px] text-slate-400 mt-2">
                      {new Date(r.created_at).toLocaleString('ru')} · {r.id}
                    </div>
                    {(newIssued || r.issued_token) && (
                      <div className="mt-3 p-3 bg-emerald-50 border border-emerald-100 rounded-lg text-sm">
                        <div className="font-semibold text-emerald-900 mb-1">Кабинет аптеки выдан:</div>
                        <div className="text-xs font-mono text-emerald-800 break-all">
                          {window.location.origin}/partner-upload?token={newIssued?.token || r.issued_token}
                        </div>
                        <button
                          onClick={() => copy(`${window.location.origin}/partner-upload?token=${newIssued?.token || r.issued_token}`)}
                          className="mt-2 text-xs flex items-center gap-1 text-emerald-700 hover:text-emerald-900"
                        >
                          <Copy className="w-3 h-3" /> Скопировать ссылку
                        </button>
                      </div>
                    )}
                  </div>
                  {r.status === 'new' && (
                    <div className="flex flex-col gap-1.5">
                      <button
                        data-testid="partner-approve"
                        onClick={() => approve(r.id)}
                        disabled={busyId === r.id}
                        className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" /> Одобрить
                      </button>
                      <button
                        data-testid="partner-reject"
                        onClick={() => reject(r.id)}
                        disabled={busyId === r.id}
                        className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg border border-rose-200 text-rose-700 hover:bg-rose-50"
                      >
                        <XCircle className="w-3.5 h-3.5" /> Отклонить
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
