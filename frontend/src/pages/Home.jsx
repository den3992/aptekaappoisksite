import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Search, MapPin, ShieldCheck, ArrowRight, Pill } from 'lucide-react';
import { useCity } from '../context/CityContext';
import CategoryIcon from '../components/CategoryIcon';
import PillIcon from '../components/PillIcon';
import PartnersMarquee from '../components/PartnersMarquee';
import SEOHead from '../components/SEOHead';
import { homeSEO } from '../seo';
import { suggestMeds, fetchCategories } from '../api/client';
import { getCategoryStyle } from '../lib/categoryStyles';

const POPULAR_QUERIES = ['Парацетамол', 'Нурофен', 'Витамин D3', 'Омепразол', 'Кагоцел', 'Смекта'];

export default function Home() {
  const { city, cities, setCity } = useCity();
  const { city: cityParam } = useParams();
  const [q, setQ] = useState('');
  const [apiSuggestions, setApiSuggestions] = useState([]);
  const [popularMeds, setPopularMeds] = useState([]);
  const [categories, setCategories] = useState([]);
  const navigate = useNavigate();

  // Sync URL city → context
  useEffect(() => {
    if (cityParam && cities) {
      const found = cities.find(c => c.id === cityParam);
      if (found && found.id !== city.id) setCity(found);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cityParam]);

  // API-backed suggestions (typeahead in search box)
  useEffect(() => {
    if (!q || q.trim().length < 2) { setApiSuggestions([]); return; }
    let cancelled = false;
    const t = setTimeout(() => {
      suggestMeds(q.trim()).then((d) => { if (!cancelled) setApiSuggestions(d); }).catch(() => {});
    }, 200);
    return () => { cancelled = true; clearTimeout(t); };
  }, [q]);

  // Popular medications: pick the best match from /api/search/suggest for each curated query
  useEffect(() => {
    let cancelled = false;
    Promise.all(
      POPULAR_QUERIES.map(query =>
        suggestMeds(query).then(arr => arr && arr[0]).catch(() => null)
      )
    ).then(arr => {
      if (!cancelled) setPopularMeds(arr.filter(Boolean));
    });
    return () => { cancelled = true; };
  }, []);

  // Categories for the homepage block
  useEffect(() => {
    fetchCategories()
      .then(arr => setCategories(arr.filter(c => c.slug !== 'other')))
      .catch(() => setCategories([]));
  }, []);

  const suggestions = apiSuggestions;

  const submit = (e) => {
    e.preventDefault();
    if (q.trim()) navigate(`/${city.id}/poisk?q=${encodeURIComponent(q.trim())}`);
  };

  const seo = homeSEO(city.id);
  const websiteJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    name: 'АптекаА',
    url: seo.canonical,
    potentialAction: {
      '@type': 'SearchAction',
      target: `${seo.canonical}/poisk?q={search_term_string}`,
      'query-input': 'required name=search_term_string',
    },
  };

  return (
    <div>
      <SEOHead seo={{ ...seo, jsonLd: websiteJsonLd }} />
      {/* Hero block (brand + hero combined with single smooth gradient) */}
      <div className="relative bg-gradient-to-b from-emerald-50/70 via-emerald-50/40 to-white overflow-hidden border-b border-slate-100">
        {/* decorative shapes */}
        <div aria-hidden="true" className="pointer-events-none absolute inset-0">
          <div className="absolute top-20 -left-16 w-96 h-96 rounded-full bg-emerald-200/25 blur-3xl" />
          <div className="absolute bottom-0 -right-16 w-[28rem] h-[28rem] rounded-full bg-emerald-100/35 blur-3xl" />
          <div className="absolute top-1/3 right-12 w-3 h-3 rounded-full bg-emerald-400/60" />
          <div className="absolute top-40 right-1/4 w-2 h-2 rounded-full bg-emerald-500/50" />
          <div className="absolute bottom-32 left-1/4 w-2.5 h-2.5 rounded-full bg-emerald-400/50" />
        </div>

        {/* Brand */}
        <div className="relative max-w-7xl mx-auto px-4 pt-7 pb-2 flex justify-center">
          <Link to="/" className="inline-flex flex-col items-center leading-none">
            <div className="flex items-center gap-3">
              <PillIcon size={42} />
              <span className="text-2xl font-extrabold text-slate-900 tracking-tight">Аптека<span className="text-emerald-600">А</span></span>
            </div>
            <span className="text-sm text-slate-500 mt-2">Актуальное наличие лекарств по всей России</span>
          </Link>
        </div>

        {/* Hero */}
        <section className="relative max-w-4xl mx-auto px-4 pt-10 pb-16 md:pt-14 md:pb-24 text-center">
          <div className="inline-flex items-center gap-2 bg-white/80 backdrop-blur border border-emerald-100 rounded-full px-3.5 py-1.5 mb-6 text-xs font-medium text-emerald-800 shadow-sm">
            <ShieldCheck className="w-3.5 h-3.5" />
            Более 200 аптек-партнёров в Москве и СПб
          </div>
          <h1 className="text-4xl md:text-5xl lg:text-6xl font-extrabold tracking-tight text-slate-900 leading-[1.05]">
            Ищите лекарства <span className="text-emerald-600">быстро</span><br />и по <span className="text-emerald-600">лучшей цене</span>
          </h1>
          <p className="mt-6 text-lg text-slate-600 max-w-2xl mx-auto">
            Сравнивайте наличие и цены на лекарства, БАДы и аптечные товары в аптеках вашего города. Бесплатно и без регистрации.
          </p>

          <form onSubmit={submit} className="mt-10 mx-auto max-w-3xl bg-white shadow-card border border-slate-100 rounded-2xl p-2 flex flex-col sm:flex-row gap-2 input-focus text-left">
            <div className="flex items-center gap-2 sm:border-r sm:border-slate-100 px-3 py-2 sm:py-0">
              <MapPin className="w-4 h-4 text-emerald-600" />
              <select value={city.id} onChange={(e) => setCity(cities.find(c => c.id === e.target.value))} className="text-sm font-medium text-slate-800 bg-transparent outline-none cursor-pointer">
                {cities.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div className="flex-1 flex items-center gap-2 px-3 relative">
              <Search className="w-4 h-4 text-slate-400" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Название препарата, вещества или симптома…"
                className="w-full text-base py-3 bg-transparent outline-none"
              />
              {suggestions.length > 0 && (
                <div className="absolute left-0 right-0 top-full mt-2 bg-white border border-slate-100 rounded-xl shadow-card overflow-hidden z-10 text-left" data-testid="search-suggestions">
                  {suggestions.map(s => (
                    <Link key={s.slug} to={`/${city.id}/preparaty/${s.slug}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-emerald-50 transition" onClick={() => setQ('')}>
                      <Pill className="w-4 h-4 text-emerald-600 shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-slate-900 truncate">{s.name}</div>
                        <div className="text-xs text-slate-500 truncate">{[s.form, s.dosage, s.manufacturer].filter(Boolean).join(' · ')}</div>
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </div>
            <button type="submit" className="bg-emerald-600 hover:bg-emerald-700 text-white font-medium px-6 py-3 rounded-xl transition">
              Найти лекарство
            </button>
          </form>

          <div className="mt-5 flex items-center gap-2 flex-wrap justify-center text-xs text-slate-500">
            <span>Часто ищут:</span>
            {['Парацетамол','Нурофен','Арбидол','Витамин D3','Смекта','Зодак'].map(t => (
              <button key={t} type="button" onClick={() => navigate(`/${city.id}/poisk?q=${encodeURIComponent(t)}`)} className="px-2.5 py-1 rounded-full bg-white/70 backdrop-blur border border-slate-200 hover:border-emerald-300 hover:text-emerald-700 transition">{t}</button>
            ))}
          </div>
        </section>
      </div>

      {/* Partners marquee */}
      <PartnersMarquee />

      {/* Popular meds — uniform grid */}
      <section className="max-w-7xl mx-auto px-4 pt-12 pb-2">
        <div className="flex items-center justify-between gap-3 mb-5">
          <h2 className="text-xl md:text-2xl font-bold text-slate-900">Популярные препараты</h2>
          <Link to={`/${city.id}/preparaty`} className="text-emerald-700 text-sm font-medium hover:underline inline-flex items-center gap-1 whitespace-nowrap shrink-0">Каталог А–Я <ArrowRight className="w-4 h-4" /></Link>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5" data-testid="popular-meds">
          {popularMeds.map(m => (
            <Link key={m.slug} to={`/${city.id}/preparaty/${m.slug}`} className="group flex flex-col justify-between bg-white border border-slate-200 hover:border-emerald-400 hover:shadow-sm transition rounded-xl px-4 py-3.5 min-h-[72px]">
              <span className="font-semibold text-slate-900 text-sm leading-tight line-clamp-2">{m.name}</span>
              <span className="text-xs text-slate-500 mt-1 truncate">{[m.form?.toLowerCase(), m.dosage].filter(Boolean).join(', ')}</span>
            </Link>
          ))}
        </div>
      </section>

      {/* Categories — uniform grid */}
      <section className="max-w-7xl mx-auto px-4 pt-10 pb-12">
        <div className="flex items-center justify-between gap-3 mb-5">
          <div className="min-w-0">
            <h2 className="text-xl md:text-2xl font-bold text-slate-900">Категории препаратов</h2>
            <p className="text-slate-500 text-sm mt-1 hidden sm:block">Найдите препарат по своей задаче</p>
          </div>
          <Link to={`/${city.id}/kategorii`} className="text-emerald-700 text-sm font-medium hover:underline inline-flex items-center gap-1 whitespace-nowrap shrink-0">Все категории <ArrowRight className="w-4 h-4" /></Link>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-4 gap-2.5">
          {categories.slice(0, 8).map(c => {
            const style = getCategoryStyle(c.slug);
            return (
              <Link key={c.slug} to={`/${city.id}/kategorii/${c.slug}`} className="cat-card flex flex-col items-start gap-2.5 bg-white border border-slate-200 hover:border-emerald-400 transition rounded-xl px-4 py-3.5 min-h-[96px]">
                <span className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: style.color, color: style.accent }}>
                  <CategoryIcon name={style.icon} className="w-4.5 h-4.5" />
                </span>
                <span className="text-slate-900 font-semibold text-sm leading-tight">{c.title}</span>
              </Link>
            );
          })}
        </div>
      </section>

      {/* CTA for pharmacies */}
      <section className="max-w-7xl mx-auto px-4 py-14">
        <div className="bg-gradient-to-br from-emerald-600 to-emerald-700 rounded-2xl p-8 md:p-12 text-white relative overflow-hidden">
          <div className="max-w-2xl relative z-10">
            <div className="inline-block px-3 py-1 bg-white/15 rounded-full text-xs font-medium mb-4">Для аптек</div>
            <h2 className="text-3xl md:text-4xl font-bold mb-3">Привлекайте новых клиентов в вашу аптеку</h2>
            <p className="text-emerald-50 leading-relaxed mb-6">
              Привлекайте новых клиентов в свою аптеку. Простая выгрузка ассортимента. Поможем с настройкой.
            </p>
            <Link to="/dlya-aptek" className="inline-flex items-center gap-2 bg-white text-emerald-700 hover:bg-emerald-50 font-semibold px-6 py-3 rounded-xl transition">
              Подробнее <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
          <div className="absolute -right-12 -bottom-16 w-72 h-72 rounded-full bg-white/5" />
          <div className="absolute -right-24 -top-12 w-56 h-56 rounded-full bg-white/5" />
        </div>
      </section>
    </div>
  );
}
