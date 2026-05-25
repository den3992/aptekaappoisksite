import { CityProvider } from '../../context/CityContext';
import Header from '../../components/Header';
import MobileTabBar from '../../components/MobileTabBar';
import SearchOverlay from '../../components/SearchOverlay';

// Layout для всех city-prefixed маршрутов: /[city], /[city]/kategorii, ...
// CityProvider — client (нужен localStorage + state), header/tabbar/overlay
// тоже 'use client'. Сам layout — серверный: рендерит обёртки.
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
