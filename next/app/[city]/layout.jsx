import { CityProvider } from '../../context/CityContext';
import Header from '../../components/Header';
import MobileTabBar from '../../components/MobileTabBar';
import SearchOverlay from '../../components/SearchOverlay';

const CITY_NAMES = { msk: 'Москве', spb: 'Санкт-Петербурге' };
const CITY_GEN = { msk: 'Москвы', spb: 'Санкт-Петербурга' };

export async function generateMetadata({ params }) {
  const { city } = await params;
  const inLoc = CITY_NAMES[city] || 'Москве';
  const gen = CITY_GEN[city] || 'Москвы';
  return {
    title: {
      default: `Аптечная справочная ${gen} — АптекаА`,
    },
    description: `Поиск лекарств, цены и наличие в аптеках ${inLoc}. Аналоги препаратов, адреса и режим работы. Без регистрации.`,
    metadataBase: new URL('https://aptekaa.ru'),
    // canonical НЕ выставляем на уровне layout — иначе он применяется ко всем
    // вложенным роутам без переопределения, и Категории/Аптеки получат canonical
    // главной /[city]. Каждый route задаёт свой canonical в page.jsx.
    openGraph: {
      type: 'website',
      siteName: 'АптекаА',
      locale: 'ru_RU',
    },
  };
}

export default function CityLayout({ children }) {
  return (
    <CityProvider>
      <Header />
      {children}
      <MobileTabBar />
      <SearchOverlay />
    </CityProvider>
  );
}
