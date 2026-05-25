import CategoriesClient from './CategoriesClient';
const G = { msk: 'Москвы', spb: 'Санкт-Петербурга' };
export async function generateMetadata({ params }) {
  const { city } = await params;
  const g = G[city] || 'Москвы';
  return {
    title: `Категории препаратов в аптеках ${g} — АптекаА`,
    description: `Все категории лекарственных препаратов, доступные в аптеках ${g}: обезболивающие, от простуды, витамины, антибиотики и другие.`,
    alternates: { canonical: `https://aptekaa.ru/${city}/kategorii` },
  };
}
export default function Page() { return <CategoriesClient />; }
