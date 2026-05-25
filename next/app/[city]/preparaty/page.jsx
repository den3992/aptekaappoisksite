import CatalogClient from './CatalogClient';
const G = { msk: 'Москвы', spb: 'Санкт-Петербурга' };
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
