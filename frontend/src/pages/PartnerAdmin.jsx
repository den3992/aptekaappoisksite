import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import axios from 'axios';
import { CheckCircle2, XCircle, Copy, Loader2, Inbox, ShieldAlert } from 'lucide-react';
import SEOHead from '../components/SEOHead';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * Hidden admin page to review/approve partner requests.
 * Usage: /partner-admin?token=<ADMIN_TOKEN>
 */
export default function PartnerAdmin() {
  const [params] = useSearchParams();
  const token = params.get('token') || '';
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState('new');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState(null);
  const [issued, setIssued] = useState({}); // {requestId: {token, pharmacy_id}}

  const refresh = async () => {
    setLoading(true); setError('');
    try {
      const { data } = await axios.get(`${API}/admin/partner-requests`, {
        headers: { 'X-Admin-Token': token },
        params: filter !== 'all' ? { status: filter } : {},
      });
      setItems(data);
    } catch (e) {
      setError(e?.response?.status === 403 ? 'Неверный токен администратора' : 'Ошибка загрузки');
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
        headers: { 'X-Admin-Token': token },
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
        headers: { 'X-Admin-Token': token },
      });
      await refresh();
    } catch (e) {
      alert('Ошибка отклонения');
    } finally {
      setBusyId(null);
    }
  };

  const copy = (text) => {
    navigator.clipboard.writeText(text);
  };

  if (!token) {
    return (
      <div className="max-w-md mx-auto px-4 py-20 text-center">
        <SEOHead seo={{ title: 'Кабинет администратора | АптекаА' }} />
        <ShieldAlert className="w-10 h-10 text-rose-500 mx-auto mb-3" />
        <h1 className="text-xl font-bold text-slate-900 mb-2">Требуется токен</h1>
        <p className="text-slate-600 text-sm">Откройте страницу с админ-токеном в URL.</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-md mx-auto px-4 py-20 text-center">
        <ShieldAlert className="w-10 h-10 text-rose-500 mx-auto mb-3" />
        <h1 className="text-xl font-bold text-slate-900 mb-2">{error}</h1>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-4 py-8" data-testid="partner-admin-page">
      <SEOHead seo={{ title: 'Заявки партнёров | АптекаА' }} />
      <h1 className="text-2xl md:text-3xl font-bold text-slate-900 mb-1">Заявки партнёров</h1>
      <p className="text-slate-500 text-sm mb-6">Скрытая страница администратора. Не индексируется.</p>

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
