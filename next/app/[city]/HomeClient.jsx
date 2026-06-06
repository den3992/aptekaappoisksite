'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useParams } from 'next/navigation';
import NotFound from '../../components/NotFound';
import { ShieldCheck, ArrowRight, Pill, Building2, Sparkles, Map, Search } from 'lucide-react';
import { useCity } from '../../context/CityContext';
import CategoryIcon from '../../components/CategoryIcon';
import { suggestMeds, fetchCategories } from '../../api/client';
import { formatName } from '../../utils/text';
import { getCategoryStyle } from '../../lib/categoryStyles';
import PartnersMarquee from '../../components/PartnersMarquee';
import LeadModal from '../../components/LeadModal';

const POPULAR_QUERIES = ['Парацетамол', 'Нурофен', 'Витамин D3', 'Омепразол', 'Кагоцел', 'Смекта'];

const TRUST_SIGNALS = [
  { icon: ShieldCheck, text: 'Тысячи аптек в 10 городах России' },
  { icon: Pill, text: 'Более 23 000 препаратов в каталоге' },
  { icon: Building2, text: '7 аптечных сетей в каталоге' },
  { icon: Map, text: 'Цены и наличие на интерактивной карте' },
  { icon: Sparkles, text: 'Бесплатно и без регистрации' },
];

const CITY_GEN = {
  msk: 'Москвы', moskva: 'Москвы',
  spb: 'Санкт-Петербурга', 'sankt-peterburg': 'Санкт-Петербурга',
  krd: 'Краснодара', krasnodar: 'Краснодара',
  nn: 'Нижнего Новгорода', 'nizhniy-novgorod': 'Нижнего Новгорода',
  ekb: 'Екатеринбурга', kzn: 'Казани', nsk: 'Новосибирска',
  sam: 'Самары', chel: 'Челябинска', ufa: 'Уфы',
  rnd: 'Ростова-на-Дону', vrn: 'Воронежа',
};

export default function Home() {
  const { city, cities, setCity } = useCity();
  const { city: cityParam } = useParams();
  // cityParam (из URL) доступен и при SSR — H1 сразу корректен для бота;
  // city из контекста на сервере ещё дефолтный (msk), поэтому он лишь фолбэк.
  const cityGen = CITY_GEN[cityParam] || CITY_GEN[city?.id] || 'Москвы';
  const [popularMeds, setPopularMeds] = useState([]);
  const [leadOpen, setLeadOpen] = useState(false);
  const [categories, setCategories] = useState([]);
  const router = useRouter();

  const [trustIdx, setTrustIdx] = useState(0);
  const [trustVisible, setTrustVisible] = useState(true);
  useEffect(() => {
    const t = setInterval(() => {
      setTrustVisible(false);
      setTimeout(() => {
        setTrustIdx(i => (i + 1) % TRUST_SIGNALS.length);
        setTrustVisible(true);
      }, 250);
    }, 3000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (cityParam && cities && cities.length > 0) {
      const slugToId = {
        moskva: 'msk', msk: 'msk',
        'sankt-peterburg': 'spb', spb: 'spb',
        krasnodar: 'krd', krd: 'krd',
        'nizhniy-novgorod': 'nn', nn: 'nn',
      };
      const targetId = slugToId[cityParam];
      if (targetId) {
        const found = cities.find(c => c.id === targetId);
        if (found && found.id !== city.id) setCity(found);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cityParam, cities]);

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

  useEffect(() => {
    fetchCategories()
      .then(arr => setCategories(arr.filter(c => c.slug !== 'other')))
      .catch(() => setCategories([]));
  }, []);

  useEffect(() => {
    document.body.classList.add('home-bg');
    return () => document.body.classList.remove('home-bg');
  }, []);

  if (cityParam && !['moskva', 'msk', 'spb', 'sankt-peterburg', 'krd', 'krasnodar', 'nn', 'nizhniy-novgorod'].includes(cityParam)) {
    return <NotFound />;
  }

  return (
    <div>
      <div className="relative overflow-hidden bg-gradient-to-b from-emerald-50/70 via-emerald-50/40 to-white border-b border-slate-100">
        <div aria-hidden="true" className="pointer-events-none absolute inset-0">
          <div className="absolute top-20 -left-16 w-96 h-96 rounded-full bg-emerald-200/25 blur-3xl" />
          <div className="absolute bottom-0 -right-16 w-[28rem] h-[28rem] rounded-full bg-emerald-100/35 blur-3xl" />
        </div>

        {/* Hero text */}
        <section className="relative z-20 max-w-4xl mx-auto px-4 pt-6 pb-10 md:pt-14 md:pb-24 text-center">
          {(() => {
            const TrustIcon = TRUST_SIGNALS[trustIdx].icon;
            return (
              <div aria-live="polite" data-testid="hero-trust-badge" className={`inline-flex items-center gap-2 bg-white/80 backdrop-blur border border-emerald-100 rounded-full px-3 py-1 mb-4 md:mb-6 text-[11px] md:text-xs font-medium text-emerald-800 shadow-sm transition-opacity duration-300 ${trustVisible ? 'opacity-100' : 'opacity-0'}`}>
                <TrustIcon className="w-3.5 h-3.5 shrink-0" />
                <span className="whitespace-nowrap">{TRUST_SIGNALS[trustIdx].text}</span>
              </div>
            );
          })()}
          <h1 className="text-3xl sm:text-4xl md:text-5xl lg:text-6xl font-extrabold tracking-tight text-slate-900 leading-[1.1] md:leading-[1.05]">
            Лекарства в аптеках {cityGen}:<br /><span className="text-emerald-600">цены и наличие</span>
          </h1>
          <p className="mt-4 md:mt-6 text-base md:text-lg text-slate-600 max-w-2xl mx-auto">
            Бесплатная аптечная справочная по крупным городам России. Сравнивайте наличие и цены на лекарства, БАДы и аптечные товары. Без регистрации.
          </p>

          <div className="hidden md:flex mt-10 items-center gap-2 flex-wrap justify-center text-xs text-slate-500">
            <span>Часто ищут:</span>
            {['Парацетамол','Нурофен','Арбидол','Витамин D3','Смекта','Зодак'].map(t => (
              <button key={t} type="button" onClick={() => router.push(`/${city.id}/poisk?q=${encodeURIComponent(t)}`)} className="px-2.5 py-1 rounded-full bg-white/70 backdrop-blur border border-slate-200 hover:border-emerald-300 hover:text-emerald-700 transition">{t}</button>
            ))}
          </div>
        </section>
        {/* Partners marquee — внутри градиента, чтобы фон перетекал */}
        <PartnersMarquee />
      </div>

      {/* Popular meds */}
      <section className="hidden md:block max-w-7xl mx-auto px-4 pt-8 md:pt-12 pb-2">
        <div className="flex items-center justify-between gap-3 mb-5">
          <h2 className="text-xl md:text-2xl font-bold text-slate-900">Популярные препараты</h2>
          <Link href={`/${city.id}/preparaty`} className="text-emerald-700 text-sm font-medium hover:underline inline-flex items-center gap-1 whitespace-nowrap shrink-0">Каталог А–Я <ArrowRight className="w-4 h-4" /></Link>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5" data-testid="popular-meds">
          {popularMeds.map(m => (
            <Link key={m.slug} href={`/${city.id}/preparaty/${m.slug}`} className="group flex flex-col justify-between bg-white border border-slate-200 hover:border-emerald-400 hover:shadow-sm transition rounded-xl px-4 py-3.5 min-h-[72px]">
              <span className="font-semibold text-slate-900 text-sm leading-tight line-clamp-2">{formatName(m.name)}</span>
              <span className="text-xs text-slate-500 mt-1 truncate">{[m.form?.toLowerCase(), m.dosage].filter(Boolean).join(', ')}</span>
            </Link>
          ))}
        </div>
      </section>

      {/* Categories */}
      <section className="hidden md:block max-w-7xl mx-auto px-4 pt-8 md:pt-10 pb-10 md:pb-12">
        <div className="flex items-center justify-between gap-3 mb-5">
          <div className="min-w-0">
            <h2 className="text-xl md:text-2xl font-bold text-slate-900">Категории препаратов</h2>
            <p className="text-slate-500 text-sm mt-1 hidden sm:block">Найдите препарат по своей задаче</p>
          </div>
          <Link href={`/${city.id}/kategorii`} className="text-emerald-700 text-sm font-medium hover:underline inline-flex items-center gap-1 whitespace-nowrap shrink-0">Все категории <ArrowRight className="w-4 h-4" /></Link>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-4 gap-2.5">
          {categories.slice(0, 8).map(c => {
            const style = getCategoryStyle(c.slug);
            return (
              <Link key={c.slug} href={`/${city.id}/kategorii/${c.slug}`} className="cat-card flex flex-col items-start gap-2.5 bg-white border border-slate-200 hover:border-emerald-400 transition rounded-xl px-4 py-3.5 min-h-[96px]">
                <span className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: style.color, color: style.accent }}>
                  <CategoryIcon name={style.icon} className="w-4.5 h-4.5" />
                </span>
                <span className="text-slate-900 font-semibold text-sm leading-tight">{c.title}</span>
              </Link>
            );
          })}
        </div>
      </section>

      {/* CTA: заявка на поиск лекарства */}
      <section className="max-w-7xl mx-auto px-4 py-10 md:py-14">
        <div className="bg-gradient-to-br from-emerald-600 to-emerald-700 rounded-2xl p-6 md:p-12 text-white relative overflow-hidden">
          <div className="max-w-2xl relative z-10">
            <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-white/15 rounded-full text-xs font-medium mb-4">
              <Search className="w-3.5 h-3.5" /> Не нашли лекарство?
            </div>
            <h2 className="text-2xl md:text-4xl font-bold mb-3">Найдём нужный препарат в ближайшей к вам аптеке</h2>
            <p className="text-emerald-50 leading-relaxed mb-6 max-w-xl">
              Оставьте заявку — найдём, где лекарство есть в наличии рядом с вами, и сообщим.
            </p>
            <button
              type="button"
              onClick={() => setLeadOpen(true)}
              data-testid="home-lead-btn"
              className="inline-flex items-center gap-2 bg-white text-emerald-700 hover:bg-emerald-50 font-semibold px-6 py-3 rounded-xl transition"
            >
              <Search className="w-4 h-4" /> Оставить заявку на поиск лекарства
            </button>
          </div>
          <div className="absolute -right-12 -bottom-16 w-72 h-72 rounded-full bg-white/5" />
          <div className="absolute -right-24 -top-12 w-56 h-56 rounded-full bg-white/5" />
        </div>
      </section>
      <LeadModal open={leadOpen} onClose={() => setLeadOpen(false)} city={cityParam || (city && city.id)} />
    </div>
  );
}
