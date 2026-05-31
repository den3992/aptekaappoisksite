import PharmaciesListClient from './PharmaciesListClient';
const G = { msk: 'Москвы', spb: 'Санкт-Петербурга', krd: 'Краснодара', nn: 'Нижнего Новгорода' };
export async function generateMetadata({ params }) {
  const { city } = await params;
  const g = G[city] || 'Москвы';
  return {
    title: `Аптеки ${g} — адреса, телефоны, режим работы — АптекаА`,
    description: `Сеть аптек ${g}: адреса, телефоны, часы работы, поиск лекарств в наличии.`,
    alternates: { canonical: `https://aptekaa.ru/${city}/apteki` },
  };
}
export default function Page() { return <PharmaciesListClient />; }
