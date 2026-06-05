import SearchClient from './SearchClient';
const G = { msk: 'Москвы', spb: 'Санкт-Петербурга', krd: 'Краснодара', nn: 'Нижнего Новгорода', ekb: 'Екатеринбурга', kzn: 'Казани', nsk: 'Новосибирска', sam: 'Самары', chel: 'Челябинска', ufa: 'Уфы' };
export async function generateMetadata({ params }) {
  const { city } = await params;
  const g = G[city] || 'Москвы';
  return {
    title: `Поиск лекарств в аптеках ${g} — АптекаА`,
    description: `Найдите лекарственный препарат в аптеках ${g}: сравнение цен, наличие, аналоги. Бесплатно, без регистрации.`,
    alternates: { canonical: `https://aptekaa.ru/${city}/poisk` },
    robots: { index: false, follow: true }, // search results — не индексируются
  };
}
export default function Page() { return <SearchClient />; }
