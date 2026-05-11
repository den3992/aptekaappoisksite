import React, { useEffect, useState, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import axios from 'axios';
import { Upload, FileText, AlertTriangle, CheckCircle2, Loader2, History, FileWarning } from 'lucide-react';
import SEOHead from '../components/SEOHead';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * Partner upload page. Hidden — accessed only via /partner-upload?token=XXXX.
 * NOT linked from the main site navigation.
 */
export default function PartnerUpload() {
  const [params] = useSearchParams();
  const token = params.get('token') || '';
  const [me, setMe] = useState(null);
  const [meError, setMeError] = useState('');
  const [history, setHistory] = useState([]);
  const [unmatched, setUnmatched] = useState([]);
  const [tab, setTab] = useState('upload'); // upload | history | unmatched
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const [uploadError, setUploadError] = useState('');
  const [progress, setProgress] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef(null);

  useEffect(() => {
    if (!token) { setMeError('Не указан токен.'); return; }
    axios.get(`${API}/upload/me/${token}`)
      .then((r) => setMe(r.data))
      .catch((e) => setMeError(e?.response?.data?.detail || 'Ошибка авторизации.'));
  }, [token]);

  const refresh = () => {
    if (!token) return;
    axios.get(`${API}/upload/history/${token}`).then((r) => setHistory(r.data)).catch(() => {});
    axios.get(`${API}/upload/unmatched/${token}`).then((r) => setUnmatched(r.data)).catch(() => {});
  };

  useEffect(() => { if (me) refresh(); }, [me]);

  const handleFile = async (file) => {
    if (!file) return;
    setUploadError(''); setUploadResult(null); setUploading(true); setProgress(0);
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await axios.post(`${API}/upload/prices/${token}`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (p) => {
          if (p.total) setProgress(Math.round((p.loaded / p.total) * 100));
        },
        timeout: 120000,
      });
      setUploadResult(res.data);
      refresh();
    } catch (e) {
      setUploadError(e?.response?.data?.detail || 'Ошибка загрузки. Проверьте формат файла.');
    } finally {
      setUploading(false);
    }
  };

  if (meError) {
    return (
      <div className="max-w-md mx-auto px-4 py-20 text-center">
        <SEOHead seo={{ title: 'Кабинет аптеки | АптекаА' }} />
        <AlertTriangle className="w-10 h-10 text-rose-500 mx-auto mb-3" />
        <h1 className="text-xl font-bold text-slate-900 mb-2">Доступ запрещён</h1>
        <p className="text-slate-600 text-sm">{meError}</p>
        <p className="text-xs text-slate-400 mt-4">
          Если вы партнёрская аптека и не получили рабочую ссылку — напишите на partner@aptekaa.ru
        </p>
      </div>
    );
  }

  if (!me) {
    return (
      <div className="max-w-md mx-auto px-4 py-20 text-center text-slate-500">
        <Loader2 className="w-6 h-6 animate-spin mx-auto" />
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8" data-testid="partner-upload-page">
      <SEOHead seo={{ title: `Кабинет аптеки — ${me.pharmacy_name} | АптекаА`, canonical: '' }} />
      <div className="mb-6">
        <div className="text-xs uppercase tracking-wide text-emerald-700 font-semibold mb-1">Кабинет аптеки‑партнёра</div>
        <h1 className="text-2xl md:text-3xl font-bold text-slate-900">{me.pharmacy_name}</h1>
        <p className="text-sm text-slate-500 mt-1">
          Город: {me.city === 'msk' ? 'Москва' : me.city === 'spb' ? 'Санкт‑Петербург' : me.city || '—'} ·
          Сеть: {me.chain || '—'} · ID: {me.pharmacy_id}
        </p>
      </div>

      {/* Tabs */}
      <div className="border-b border-slate-200 mb-6 flex gap-1">
        {[
          { id: 'upload', label: 'Загрузка прайса', icon: Upload },
          { id: 'history', label: `История (${history.length})`, icon: History },
          { id: 'unmatched', label: `Требуют разбора (${unmatched.length})`, icon: FileWarning },
        ].map(t => (
          <button
            key={t.id}
            data-testid={`partner-tab-${t.id}`}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2.5 text-sm font-medium flex items-center gap-2 border-b-2 -mb-px transition ${
              tab === t.id
                ? 'border-emerald-600 text-emerald-700'
                : 'border-transparent text-slate-500 hover:text-slate-800'
            }`}
          >
            <t.icon className="w-4 h-4" /> {t.label}
          </button>
        ))}
      </div>

      {/* Upload tab */}
      {tab === 'upload' && (
        <div>
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault(); setDragOver(false);
              const f = e.dataTransfer.files?.[0];
              if (f) handleFile(f);
            }}
            className={`border-2 border-dashed rounded-2xl p-12 text-center transition ${
              dragOver ? 'border-emerald-400 bg-emerald-50/40' : 'border-slate-300 bg-white'
            }`}
          >
            <Upload className="w-10 h-10 mx-auto text-emerald-600 mb-3" />
            <h2 className="text-lg font-semibold text-slate-900 mb-1">
              {uploading ? `Загружаю… ${progress}%` : 'Перетащите файл XLSX или CSV'}
            </h2>
            <p className="text-sm text-slate-500 mb-4">или</p>
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx,.csv"
              className="hidden"
              data-testid="partner-file-input"
              onChange={(e) => handleFile(e.target.files?.[0])}
            />
            <button
              data-testid="partner-pick-file"
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
              className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg font-medium disabled:opacity-50"
            >
              Выбрать файл
            </button>
            {uploading && (
              <div className="mt-4 w-full bg-slate-100 rounded-full h-2 overflow-hidden">
                <div className="h-full bg-emerald-500 transition-all" style={{ width: `${progress}%` }} />
              </div>
            )}
          </div>

          {/* Format helper */}
          <div className="mt-6 bg-blue-50 border border-blue-100 rounded-xl p-5 text-sm text-blue-900">
            <h3 className="font-semibold mb-2">Формат файла</h3>
            <p className="mb-2">Заголовки колонок (английские или русские, в любом порядке):</p>
            <table className="text-xs w-full">
              <thead className="text-left text-blue-700 uppercase">
                <tr>
                  <th className="py-1 pr-4">Колонка</th>
                  <th className="py-1 pr-4">Английский</th>
                  <th className="py-1 pr-4">Русский</th>
                  <th className="py-1">Обязат.</th>
                </tr>
              </thead>
              <tbody>
                <tr><td className="py-1 pr-4 font-medium">Штрихкод</td><td className="py-1 pr-4 font-mono">gtin</td><td className="py-1 pr-4">штрихкод, ean</td><td className="py-1">да</td></tr>
                <tr><td className="py-1 pr-4 font-medium">Название</td><td className="py-1 pr-4 font-mono">name</td><td className="py-1 pr-4">название, наименование</td><td className="py-1">да</td></tr>
                <tr><td className="py-1 pr-4 font-medium">Количество</td><td className="py-1 pr-4 font-mono">qty</td><td className="py-1 pr-4">количество, кол-во, остаток</td><td className="py-1">да</td></tr>
                <tr><td className="py-1 pr-4 font-medium">Цена</td><td className="py-1 pr-4 font-mono">price</td><td className="py-1 pr-4">цена, стоимость</td><td className="py-1">да</td></tr>
                <tr><td className="py-1 pr-4 font-medium">Код аптеки</td><td className="py-1 pr-4 font-mono">pharmacy_id</td><td className="py-1 pr-4">код аптеки, точка</td><td className="py-1">нет</td></tr>
                <tr><td className="py-1 pr-4 font-medium">Срок годности</td><td className="py-1 pr-4 font-mono">expiry_date</td><td className="py-1 pr-4">срок годности, годен до</td><td className="py-1">нет</td></tr>
              </tbody>
            </table>
            <p className="mt-3 text-xs">
              CSV принимаем в кодировке UTF‑8 или Windows‑1251. Размер — до 25 МБ. Каждая загрузка перезаписывает предыдущие
              цены/остатки этой аптеки. Препараты, GTIN которых нет в реестре mdlp, попадают во вкладку «Требуют разбора».
            </p>
          </div>

          {/* Result panel */}
          {uploadError && (
            <div className="mt-6 bg-rose-50 border border-rose-200 rounded-xl p-5" data-testid="partner-upload-error">
              <div className="flex items-start gap-3">
                <AlertTriangle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
                <div>
                  <h3 className="font-semibold text-rose-900">Ошибка загрузки</h3>
                  <p className="text-sm text-rose-800 mt-1">{uploadError}</p>
                </div>
              </div>
            </div>
          )}
          {uploadResult && (
            <div className="mt-6 bg-emerald-50 border border-emerald-200 rounded-xl p-5" data-testid="partner-upload-success">
              <div className="flex items-start gap-3">
                <CheckCircle2 className="w-6 h-6 text-emerald-600 shrink-0 mt-0.5" />
                <div className="flex-1">
                  <h3 className="font-semibold text-emerald-900">Файл загружен</h3>
                  <p className="text-sm text-emerald-800 mt-0.5">ID: {uploadResult.upload_id}</p>
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mt-4 text-sm">
                    <Stat label="Всего строк" value={uploadResult.summary.total_rows} />
                    <Stat label="Валидных" value={uploadResult.summary.valid_rows} accent="emerald" />
                    <Stat label="С ошибками" value={uploadResult.summary.invalid_rows} accent={uploadResult.summary.invalid_rows ? 'rose' : 'slate'} />
                    <Stat label="Сопоставлено" value={uploadResult.summary.matched} accent="emerald" />
                    <Stat label="Требуют разбора" value={uploadResult.summary.unmatched} accent={uploadResult.summary.unmatched ? 'amber' : 'slate'} />
                  </div>
                  {uploadResult.sample_errors.length > 0 && (
                    <details className="mt-4 text-sm">
                      <summary className="cursor-pointer font-semibold text-rose-700">Примеры строк с ошибками ({uploadResult.sample_errors.length})</summary>
                      <ul className="mt-2 text-xs text-slate-700 space-y-1">
                        {uploadResult.sample_errors.map((r, i) => (
                          <li key={i}>Строка {r.row_num}: {r.error} {r.name ? `(${r.name})` : ''}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* History tab */}
      {tab === 'history' && (
        <div className="bg-white border border-slate-100 rounded-xl overflow-hidden" data-testid="partner-history-table">
          {history.length === 0 ? (
            <div className="px-6 py-12 text-center text-slate-500 text-sm">
              <FileText className="w-8 h-8 mx-auto text-slate-300 mb-2" />
              Загрузок ещё нет
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
                <tr>
                  <th className="px-4 py-3 text-left">Дата</th>
                  <th className="px-4 py-3 text-left">Файл</th>
                  <th className="px-4 py-3 text-right">Строк</th>
                  <th className="px-4 py-3 text-right">Ошибок</th>
                  <th className="px-4 py-3 text-right">Сопоставлено</th>
                  <th className="px-4 py-3 text-right">Разбор</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {history.map((h) => (
                  <tr key={h.upload_id} className="hover:bg-slate-50/50">
                    <td className="px-4 py-2.5 whitespace-nowrap">{new Date(h.uploaded_at).toLocaleString('ru')}</td>
                    <td className="px-4 py-2.5">{h.filename}</td>
                    <td className="px-4 py-2.5 text-right">{h.summary?.total_rows ?? '—'}</td>
                    <td className="px-4 py-2.5 text-right text-rose-600">{h.summary?.invalid_rows ?? 0}</td>
                    <td className="px-4 py-2.5 text-right text-emerald-700 font-medium">{h.summary?.matched ?? 0}</td>
                    <td className="px-4 py-2.5 text-right text-amber-700">{h.summary?.unmatched ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Unmatched tab */}
      {tab === 'unmatched' && (
        <div className="bg-white border border-slate-100 rounded-xl overflow-hidden" data-testid="partner-unmatched-table">
          {unmatched.length === 0 ? (
            <div className="px-6 py-12 text-center text-slate-500 text-sm">
              <CheckCircle2 className="w-8 h-8 mx-auto text-emerald-400 mb-2" />
              Все загруженные товары успешно сопоставлены
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
                <tr>
                  <th className="px-4 py-3 text-left">GTIN</th>
                  <th className="px-4 py-3 text-left">Название из файла</th>
                  <th className="px-4 py-3 text-right">Цена</th>
                  <th className="px-4 py-3 text-right">Кол-во</th>
                  <th className="px-4 py-3 text-left">Загружено</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {unmatched.slice(0, 200).map((u, i) => (
                  <tr key={i} className="hover:bg-slate-50/50">
                    <td className="px-4 py-2.5 font-mono text-xs">{u.gtin}</td>
                    <td className="px-4 py-2.5">{u.name_in_file}</td>
                    <td className="px-4 py-2.5 text-right">{u.price} ₽</td>
                    <td className="px-4 py-2.5 text-right">{u.qty}</td>
                    <td className="px-4 py-2.5 text-xs text-slate-500">{new Date(u.uploaded_at).toLocaleString('ru')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, accent = 'slate' }) {
  const colors = {
    slate: 'text-slate-700',
    emerald: 'text-emerald-700',
    rose: 'text-rose-700',
    amber: 'text-amber-700',
  };
  return (
    <div className="bg-white rounded-lg p-2.5 border border-emerald-100">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`text-xl font-bold ${colors[accent]}`}>{value}</div>
    </div>
  );
}
