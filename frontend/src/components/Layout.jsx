import React from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Header from './Header';
import Footer from './Footer';

export default function Layout() {
  const location = useLocation();
  const isHome = location.pathname === '/';
  return (
    <div className="min-h-screen flex flex-col bg-white">
      {!isHome && <Header />}
      <main className="flex-1"><Outlet /></main>
      <Footer />
    </div>
  );
}
