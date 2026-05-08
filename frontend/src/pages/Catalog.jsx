import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { MEDICATIONS } from '../mock';
import { Search } from 'lucide-react';

const LETTERS = ['А','Б','В','Г','Д','Е','Ж','З','И','К','Л','М','Н','О','П','Р','С','Т','У','Ф','Х','Ц','Ч','Ш','Щ','Э','Ю','Я'];

export default function Catalog() {
  const [q, setQ] = useState('');
  const [letter, setLetter] = useState('');

  const filtered = useMemo(() => {
    let arr = [...MEDICATIONS].sort((a,b) => a.name.localeCompare(b.name, 'ru'));
    if (letter) arr = arr.filter(m => m.name.toUpperCase().startsWith(letter));
    if (q) arr = arr.filter(m => m.name.toLowerCase().includes(q.toLowerCase()) || m.mnn.toLowerCase().includes(q.toLowerCase()));
    return arr;
  }, [letter, q]);

  const grouped = useMemo(() => {
    const map = {};
    filtered.forEach(m => {
      const ch = m.name[0].toUpperCase();
      (map[ch] = map[ch] || []).push(m);
    });
    return map;
  }, [filtered]);

  const availableLetters = useMemo(() => {
    const s = new Set(MEDICATIONS.map(m => m.name[0].toUpperCase()));
    return s;
  }, []);

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <nav className="text-xs text-slate-500 mb-4">
        <Link to="/" className="hover:text-emerald-700">Главная</Link>
        <span className="mx-1.5">/</span><span>Каталог препаратов</span>
      </nav>
      <h1 className="text-3xl md:text-4xl font-bold text-slate-900 mb-2">Каталог лекарств А–Я</h1>
      <p className="text-slate-500 mb-6">Все препараты в алфавитном порядке</p>

      <div className="input-focus border border-slate-200 rounded-lg flex items-center bg-white max-w-md mb-6 transition">
        <Search className="w-4 h-4 text-slate-400 ml-3" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Найти в каталоге…" className="flex-1 px-3 py-2.5 text-sm bg-transparent outline-none" />
      </div>

      <div className="flex flex-wrap gap-1.5 mb-8 bg-white border border-slate-100 rounded-xl p-3">
        <button onClick={() => setLetter('')} className={`px-3 py-1.5 text-sm rounded-md ${!letter ? 'bg-emerald-600 text-white' : 'hover:bg-emerald-50'}`}>Все</button>
        {LETTERS.map(l => {
          const active = letter === l;
          const enabled = availableLetters.has(l);
          return (
            <button key={l} disabled={!enabled} onClick={() => setLetter(l)} className={`w-9 h-9 text-sm rounded-md font-medium ${active ? 'bg-emerald-600 text-white' : enabled ? 'hover:bg-emerald-50 text-slate-700' : 'text-slate-300 cursor-not-allowed'}`}>{l}</button>
          );
        })}
      </div>

      {filtered.length === 0 ? (
        <div className="text-center text-slate-500 py-16">Ничего не найдено</div>
      ) : (
        <div className="space-y-8">
          {Object.keys(grouped).sort((a,b) => a.localeCompare(b, 'ru')).map(ch => (
            <div key={ch}>
              <h2 className="text-2xl font-bold text-emerald-700 mb-3 sticky top-32 bg-white/95 backdrop-blur z-10 py-1">{ch}</h2>
              <div className="grid sm:grid-cols-2 md:grid-cols-3 gap-2">
                {grouped[ch].map(m => (
                  <Link key={m.slug} to={`/preparaty/${m.slug}`} className="flex items-start gap-3 p-3 rounded-lg hover:bg-emerald-50/50 border border-transparent hover:border-emerald-100 transition">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-semibold text-slate-900 truncate">{m.name}</div>
                      <div className="text-xs text-slate-500 truncate">{m.form} · {m.manufacturer}</div>
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
