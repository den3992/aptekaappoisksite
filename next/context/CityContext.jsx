'use client';
import React, { createContext, useContext, useEffect, useState } from 'react';

export const CITIES = [
  { id: 'msk', name: 'Москва', inLoc: 'Москве', center: [55.751244, 37.618423], zoom: 11 },
  { id: 'spb', name: 'Санкт-Петербург', inLoc: 'Санкт-Петербурге', center: [59.9342802, 30.3350986], zoom: 11 },
];

const CityContext = createContext(null);

export const CityProvider = ({ children }) => {
  const [city, setCity] = useState(() => {
    const saved = typeof window !== 'undefined' ? window.localStorage.getItem('city') : null;
    return saved ? CITIES.find(c => c.id === saved) || CITIES[0] : CITIES[0];
  });

  useEffect(() => {
    if (city) window.localStorage.setItem('city', city.id);
  }, [city]);

  const value = { city, setCity, cities: CITIES };
  return <CityContext.Provider value={value}>{children}</CityContext.Provider>;
};

export const useCity = () => {
  const ctx = useContext(CityContext);
  // Tolerant fallback для prerender'а static-страниц (/_not-found, /о-сервисе,
  // /политики и т.д.) которые не обёрнуты в CityProvider — отдаём дефолт
  // (Москва) чтобы Link href'ы в Footer/Header не ломали build.
  if (!ctx) return { city: CITIES[0], setCity: () => {}, cities: CITIES };
  return ctx;
};
