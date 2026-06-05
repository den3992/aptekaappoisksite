import { notFound } from 'next/navigation';
import { CityProvider } from '../../context/CityContext';
import Header from '../../components/Header';
import MobileTabBar from '../../components/MobileTabBar';
import SearchOverlay from '../../components/SearchOverlay';

const CITY_NAMES = { msk: 'Москве', spb: 'Санкт-Петербурге', krd: 'Краснодаре', nn: 'Нижнем Новгороде', ekb: 'Екатеринбурге', kzn: 'Казани', nsk: 'Новосибирске', sam: 'Самаре', chel: 'Челябинске', ufa: 'Уфе' };
const CITY_GEN = { msk: 'Москвы', spb: 'Санкт-Петербурга', krd: 'Краснодара', nn: 'Нижнего Новгорода', ekb: 'Екатеринбурга', kzn: 'Казани', nsk: 'Новосибирска', sam: 'Самары', chel: 'Челябинска', ufa: 'Уфы' };
// Не импортируем CITIES из CityContext: тот модуль 'use client', и в server-
// компоненте именованный экспорт приходит client-reference прокси, а не
// массивом (TypeError: CITIES.map is not a function на build). Хардкодим.
const VALID_CITIES = ['msk', 'spb', 'krd', 'nn', 'ekb', 'kzn', 'nsk', 'sam', 'chel', 'ufa'];

export async function generateMetadata({ params }) {
  const { city } = await params;
  const inLoc = CITY_NAMES[city] || 'Москве';
  const gen = CITY_GEN[city] || 'Москвы';
  return {
    title: {
      default: `Аптечная справочная ${gen} — АптекаА`,
    },
    description: `Поиск лекарств, цены и наличие в аптеках ${gen}. Аналоги препаратов, адреса и режим работы. Без регистрации.`,
    metadataBase: new URL('https://aptekaa.ru'),
    // canonical НЕ выставляем на уровне layout — иначе он применяется ко всем
    // вложенным роутам без переопределения, и Категории/Аптеки получат canonical
    // главной /[city]. Каждый route задаёт свой canonical в page.jsx.
    openGraph: {
      type: 'website',
      siteName: 'АптекаА',
      locale: 'ru_RU',
      images: [{ url: '/og-image.png?v=2', width: 512, height: 512 }],
    },
  };
}

export default async function CityLayout({ children, params }) {
  // Алиасы /moskva, /sankt-peterburg редиректит edge nginx (301 → /msk, /spb).
  // Сюда доходят только msk/spb либо мусор. Невалидный город → notFound(),
  // чтобы Next.js отдал HTTP 404 вместо soft-404 (200 + контент «404»).
  const { city } = await params;
  if (!VALID_CITIES.includes(city)) notFound();

  return (
    <CityProvider>
      <Header />
      {children}
      <MobileTabBar />
      <SearchOverlay />
    </CityProvider>
  );
}
