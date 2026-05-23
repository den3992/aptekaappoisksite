import React from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Header from './Header';
import Footer from './Footer';
import VoiceAssistant from './VoiceAssistant';
import MobileTabBar from './MobileTabBar';
import SearchOverlay from './SearchOverlay';

export default function Layout() {
  const location = useLocation();
  const isHome = location.pathname === '/' || /^\/[a-z-]+\/?$/.test(location.pathname);
  return (
    <div className="min-h-[100dvh] flex flex-col bg-white overflow-x-clip">
      {/* На главной (desktop + мобильный) шапка не рендерится — у главной
          собственный hero (логотип, город, поиск), который не липнет.
          На остальных страницах sticky-шапка работает как обычно. */}
      {!isHome && <Header />}
      <main className="flex-1"><Outlet /></main>
      <Footer />
      <VoiceAssistant />
      <MobileTabBar />
      <SearchOverlay />
    </div>
  );
}
