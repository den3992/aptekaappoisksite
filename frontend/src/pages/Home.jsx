import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Search, MapPin, ShieldCheck, Clock, Banknote, ArrowRight, TrendingUp, Pill } from 'lucide-react';
import { useCity } from '../context/CityContext';
import { CATEGORIES, MEDICATIONS } from '../mock';
import CategoryIcon from '../components/CategoryIcon';
import MedCard from '../components/MedCard';

const POPULAR = ['paracetamol-500mg','nurofen','vitamin-d3-2000','kagocel','omeprazol-20mg','smekta','zodak','aquamaris'];

export default function Home() {
  const { city, cities, setCity } = useCity();
  const [q, setQ] = useState('');
  const navigate = useNavigate();

  const popularMeds = POPULAR.map(slug => MEDICATIONS.find(m => m.slug === slug)).filter(Boolean);
  const suggestions = q.length >= 2
    ? MEDICATIONS.filter(m => m.name.toLowerCase().includes(q.toLowerCase()) || m.mnn.toLowerCase().includes(q.toLowerCase())).slice(0, 6)
    : [];

  const submit = (e) => {
    e.preventDefault();
    if (q.trim()) navigate(`/poisk?q=${encodeURIComponent(q.trim())}`);
  };

  return (
    <div>
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
          <Link to="/" className="inline-flex items-center gap-2.5">
            <div className="w-10 h-10 rounded-lg bg-emerald-600 flex items-center justify-center text-white shadow-sm">
              <Pill className="w-5 h-5" />
            </div>
            <div className="flex flex-col leading-none">
              <span className="text-xl font-bold text-slate-900">Лекарства.РФ</span>
              <span className="text-[12px] text-slate-500 mt-1">быстрый поиск в аптеках</span>
            </div>
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
                <div className="absolute left-0 right-0 top-full mt-2 bg-white border border-slate-100 rounded-xl shadow-card overflow-hidden z-10 text-left">
                  {suggestions.map(s => (
                    <Link key={s.slug} to={`/preparaty/${s.slug}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-emerald-50 transition" onClick={() => setQ('')}>
                      <Pill className="w-4 h-4 text-emerald-600 shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-slate-900 truncate">{s.name}</div>
                        <div className="text-xs text-slate-500 truncate">{s.form} · {s.manufacturer}</div>
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
              <button key={t} type="button" onClick={() => navigate(`/poisk?q=${encodeURIComponent(t)}`)} className="px-2.5 py-1 rounded-full bg-white/70 backdrop-blur border border-slate-200 hover:border-emerald-300 hover:text-emerald-700 transition">{t}</button>
            ))}
          </div>
        </section>
      </div>

      {/* Categories */}
      <section className="max-w-7xl mx-auto px-4 py-14">
        <div className="flex items-end justify-between mb-6">
          <div>
            <h2 className="text-2xl md:text-3xl font-bold text-slate-900">Категории</h2>
            <p className="text-slate-500 mt-1">Найдите препарат по своей задаче</p>
          </div>
          <Link to="/kategorii" className="text-emerald-700 text-sm font-medium hover:underline inline-flex items-center gap-1">Все категории <ArrowRight className="w-4 h-4" /></Link>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {CATEGORIES.map(c => (
            <Link key={c.slug} to={`/kategorii/${c.slug}`} className="cat-card bg-white border border-slate-100 rounded-xl p-4 flex flex-col items-start gap-3">
              <div className="w-11 h-11 rounded-lg flex items-center justify-center" style={{ background: c.color, color: c.accent }}>
                <CategoryIcon name={c.icon} className="w-5 h-5" />
              </div>
              <div className="text-sm font-semibold text-slate-900 leading-tight">{c.title}</div>
            </Link>
          ))}
        </div>
      </section>

      {/* Popular */}
      <section className="max-w-7xl mx-auto px-4 pb-16">
        <div className="flex items-end justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-emerald-50 text-emerald-700 flex items-center justify-center">
              <TrendingUp className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-2xl md:text-3xl font-bold text-slate-900">Популярные препараты</h2>
              <p className="text-slate-500 mt-1 text-sm">Цены и наличие в {city.inLoc}</p>
            </div>
          </div>
          <Link to="/preparaty" className="text-emerald-700 text-sm font-medium hover:underline inline-flex items-center gap-1">Смотреть все <ArrowRight className="w-4 h-4" /></Link>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {popularMeds.map(m => <MedCard key={m.slug} med={m} />)}
        </div>
      </section>

      {/* Why us */}
      <section className="bg-slate-50 border-y border-slate-100">
        <div className="max-w-7xl mx-auto px-4 py-14">
          <h2 className="text-2xl md:text-3xl font-bold text-slate-900 mb-2">Почему Лекарства.РФ</h2>
          <p className="text-slate-500 mb-8">Несколько причин выбрать наш сервис</p>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { icon: Search, title: 'Быстрый поиск', desc: 'Тысячи препаратов в каталоге — ответ появляется за доли секунды' },
              { icon: Banknote, title: 'Сравнение цен', desc: 'Показываем цену в каждой аптеке и помогаем экономить' },
              { icon: MapPin, title: 'Аптеки рядом', desc: 'Находите нужные лекарства в ближайших аптеках на карте' },
              { icon: Clock, title: 'Актуальные данные', desc: 'Ежедневное обновление информации о наличии' },
            ].map((f, i) => (
              <div key={i} className="bg-white border border-slate-100 rounded-xl p-5">
                <div className="w-10 h-10 rounded-lg bg-emerald-50 text-emerald-700 flex items-center justify-center mb-3">
                  <f.icon className="w-5 h-5" />
                </div>
                <h3 className="font-semibold text-slate-900 mb-1">{f.title}</h3>
                <p className="text-sm text-slate-600 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
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
