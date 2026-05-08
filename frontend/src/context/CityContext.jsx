import React, { createContext, useContext, useEffect, useState } from 'react';

export const CITIES = [
  { id: 'msk', name: 'Москва', center: [55.751244, 37.618423], zoom: 11 },
  { id: 'spb', name: 'Санкт-Петербург', center: [59.9342802, 30.3350986], zoom: 11 },
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
  if (!ctx) throw new Error('useCity must be used inside CityProvider');
  return ctx;
};
