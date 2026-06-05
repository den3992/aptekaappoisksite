'use client';
import { createContext, useContext, useEffect, useState } from 'react';
const CITIES = [
  { id: 'msk', name: 'Москва', inLoc: 'Москве', center: [55.751244, 37.618423], zoom: 11 },
  { id: 'spb', name: 'Санкт-Петербург', inLoc: 'Санкт-Петербурге', center: [59.9342802, 30.3350986], zoom: 11 },
  { id: 'krd', name: 'Краснодар', inLoc: 'Краснодаре', center: [45.03547, 38.975313], zoom: 11 },
  { id: 'nn', name: 'Нижний Новгород', inLoc: 'Нижнем Новгороде', center: [56.326797, 44.006516], zoom: 11 },
  { id: 'ekb', name: 'Екатеринбург', inLoc: 'Екатеринбурге', center: [56.838011, 60.597474], zoom: 11 },
  { id: 'kzn', name: 'Казань', inLoc: 'Казани', center: [55.796127, 49.106414], zoom: 11 },
  { id: 'nsk', name: 'Новосибирск', inLoc: 'Новосибирске', center: [55.030199, 82.920430], zoom: 11 },
  { id: 'sam', name: 'Самара', inLoc: 'Самаре', center: [53.195873, 50.100193], zoom: 11 },
  { id: 'chel', name: 'Челябинск', inLoc: 'Челябинске', center: [55.159897, 61.402554], zoom: 11 },
  { id: 'ufa', name: 'Уфа', inLoc: 'Уфе', center: [54.735152, 55.958736], zoom: 11 },
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
