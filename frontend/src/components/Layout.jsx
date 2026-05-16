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
      {/* Header is always rendered on mobile (sticky search is the primary tool).
          On desktop the home page hides it because it has its own hero search. */}
      <Header hideOnDesktop={isHome} />
      <main className="flex-1"><Outlet /></main>
      <Footer />
      <VoiceAssistant />
      <MobileTabBar />
      <SearchOverlay />
    </div>
  );
}
