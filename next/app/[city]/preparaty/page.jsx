import CatalogClient from './CatalogClient';
const G = { msk: 'Москвы', spb: 'Санкт-Петербурга', krd: 'Краснодара', nn: 'Нижнего Новгорода', ekb: 'Екатеринбурга', kzn: 'Казани', nsk: 'Новосибирска', sam: 'Самары', chel: 'Челябинска', ufa: 'Уфы', rnd: 'Ростова-на-Дону', vrn: 'Воронежа' };
export async function generateMetadata({ params }) {
  const { city } = await params;
  const g = G[city] || 'Москвы';
  return {
    title: `Каталог лекарств А–Я в аптеках ${g} — АптекаА`,
    description: `Полный алфавитный каталог лекарственных препаратов в аптеках ${g}: цены, наличие, аналоги. Бесплатно, без регистрации.`,
    alternates: { canonical: `https://aptekaa.ru/${city}/preparaty` },
  };
}
export default function Page() { return <CatalogClient />; }
