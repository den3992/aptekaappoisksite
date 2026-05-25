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
      template: '%s | АптекаА',
    },
    description: `Поиск лекарств, цены и наличие в аптеках ${inLoc}. Аналоги препаратов, адреса и режим работы. Без регистрации.`,
    metadataBase: new URL('https://aptekaa.ru'),
    alternates: { canonical: `https://aptekaa.ru/${city}` },
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
