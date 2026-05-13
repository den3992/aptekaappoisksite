import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Search, MapPin, ChevronDown, Menu, X, Pill } from 'lucide-react';
import { useCity } from '../context/CityContext';
import { suggestMeds } from '../api/client';
import { formatName, formatManufacturer } from '../utils/text';
import PillIcon from './PillIcon';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from './ui/dropdown-menu';

export default function Header() {
  const { city, setCity, cities } = useCity();
  const [q, setQ] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [open, setOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const navigate = useNavigate();
  const wrapRef = useRef(null);

  // Debounced suggestions
  useEffect(() => {
    if (!q.trim() || q.trim().length < 2) { setSuggestions([]); return; }
    let cancelled = false;
    const t = setTimeout(() => {
      suggestMeds(q.trim())
        .then((d) => { if (!cancelled) { setSuggestions(d || []); setOpen(true); } })
        .catch(() => {});
    }, 150);
    return () => { cancelled = true; clearTimeout(t); };
  }, [q]);

  // Close on outside click / Escape
  useEffect(() => {
    const onClick = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, []);

  const onSubmit = (e) => {
    e.preventDefault();
    if (!q.trim()) return;
    setOpen(false);
    navigate(`/${city.id}/poisk?q=${encodeURIComponent(q.trim())}`);
  };

  const pickSuggestion = () => { setQ(''); setOpen(false); };

  return (
    <header className="sticky top-0 z-40 bg-white border-b border-slate-100">
      {/* main bar */}
      <div className="max-w-7xl mx-auto px-4 h-16 flex items-center gap-3 md:gap-6">
        <Link to="/" className="flex flex-col items-start leading-none shrink-0">
          <div className="flex items-center gap-2 md:gap-2.5">
            <PillIcon className="w-4 h-4 md:w-5 md:h-5" />
            <span className="text-lg font-extrabold text-slate-900 tracking-tight" style={{ fontFamily: "'Manrope', sans-serif" }}>Аптека<span className="text-emerald-600">А</span></span>
          </div>
          <span className="text-[13px] text-slate-500 mt-1.5 hidden sm:inline">Актуальное наличие лекарств</span>
        </Link>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="hidden md:flex items-center gap-1 text-sm text-slate-700 hover:text-emerald-700 px-2 py-1 rounded-md">
              <MapPin className="w-4 h-4" />
              <span className="font-medium">{city.name}</span>
              <ChevronDown className="w-4 h-4" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-48">
            {cities.map(c => (
              <DropdownMenuItem key={c.id} onClick={() => setCity(c)} className="cursor-pointer">
                <MapPin className="w-4 h-4 mr-2" /> {c.name}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        <div ref={wrapRef} className="flex-1 max-w-2xl relative">
          <form onSubmit={onSubmit} className="input-focus border border-slate-200 rounded-lg flex items-center bg-white transition">
            <Search className="w-4 h-4 text-rose-500 ml-3" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onFocus={() => suggestions.length > 0 && setOpen(true)}
              placeholder="Найдите препарат в аптеках вашего города"
              className="flex-1 px-3 py-2.5 text-sm bg-transparent outline-none"
              data-testid="header-search-input"
            />
            <button type="submit" className="hidden sm:inline-flex items-center gap-1 text-sm font-medium text-white bg-emerald-600 hover:bg-emerald-700 px-4 py-2 m-1 rounded-md transition">
              Найти
            </button>
          </form>

          {open && suggestions.length > 0 && (
            <div
              className="absolute left-0 right-0 top-full mt-2 bg-white border border-slate-100 rounded-xl shadow-card max-h-[60vh] overflow-y-auto no-scrollbar z-50 text-left"
              data-testid="header-search-suggestions"
            >
              {suggestions.map((s) => (
                <Link
                  key={s.slug}
                  to={`/${city.id}/preparaty/${s.slug}`}
                  className="flex items-center gap-3 px-4 py-2.5 hover:bg-emerald-50 transition"
                  onClick={pickSuggestion}
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
            </div>
          )}
        </div>

        <button className="md:hidden p-2" onClick={() => setMobileOpen(v => !v)} aria-label="Меню">
          {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </button>
      </div>

      {/* sub nav */}
      <nav className="hidden md:block border-t border-slate-100 bg-white">
        <div className="max-w-7xl mx-auto px-4 h-11 flex items-center gap-6 text-sm overflow-x-auto no-scrollbar">
          <Link to="/kategorii" className="text-slate-700 hover:text-emerald-700 whitespace-nowrap">Категории</Link>
          <Link to="/preparaty" className="text-slate-700 hover:text-emerald-700 whitespace-nowrap">Все препараты А–Я</Link>
          <Link to="/kategorii/ot-prostudy" className="text-slate-700 hover:text-emerald-700 whitespace-nowrap">От простуды</Link>
          <Link to="/kategorii/obezbolivayuschie" className="text-slate-700 hover:text-emerald-700 whitespace-nowrap">Обезболивающие</Link>
          <Link to="/kategorii/vitaminy-bady" className="text-slate-700 hover:text-emerald-700 whitespace-nowrap">Витамины и БАДы</Link>
          <Link to="/kategorii/serdce" className="text-slate-700 hover:text-emerald-700 whitespace-nowrap">Сердце и сосуды</Link>
          <Link to="/kategorii/allergiya" className="text-slate-700 hover:text-emerald-700 whitespace-nowrap">Аллергия</Link>
          <Link to="/kategorii/mat-i-ditya" className="text-slate-700 hover:text-emerald-700 whitespace-nowrap">Мать и дитя</Link>
          <Link to="/apteki" className="text-slate-700 hover:text-emerald-700 whitespace-nowrap ml-auto">Найти аптеку</Link>
        </div>
      </nav>

      {/* mobile menu */}
      {mobileOpen && (
        <div className="md:hidden border-t border-slate-100 bg-white">
          <div className="px-4 py-3 flex flex-col gap-2 text-sm">
            <div className="flex items-center gap-2 py-2">
              <MapPin className="w-4 h-4 text-emerald-600" />
              <span className="text-slate-500">Город:</span>
              <select value={city.id} onChange={(e) => setCity(cities.find(c => c.id === e.target.value))} className="border border-slate-200 rounded px-2 py-1">
                {cities.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <Link onClick={() => setMobileOpen(false)} to="/kategorii" className="py-2 border-t border-slate-100">Категории</Link>
            <Link onClick={() => setMobileOpen(false)} to="/preparaty" className="py-2 border-t border-slate-100">Все препараты А–Я</Link>
            <Link onClick={() => setMobileOpen(false)} to="/apteki" className="py-2 border-t border-slate-100">Аптеки</Link>
            <Link onClick={() => setMobileOpen(false)} to="/dlya-aptek" className="py-2 border-t border-slate-100">Для аптек</Link>
            <Link onClick={() => setMobileOpen(false)} to="/o-servise" className="py-2 border-t border-slate-100">О сервисе</Link>
            <Link onClick={() => setMobileOpen(false)} to="/kontakty" className="py-2 border-t border-slate-100">Контакты</Link>
          </div>
        </div>
      )}
    </header>
  );
}
