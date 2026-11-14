import CategoriesClient from './CategoriesClient';
import { categoryListJsonLd } from '../../../lib/schemas';
import { getCategories } from '../../../lib/catalogData';
export const dynamic = 'force-dynamic';
const G = { msk: 'Москвы', spb: 'Санкт-Петербурга', krd: 'Краснодара', nn: 'Нижнего Новгорода', ekb: 'Екатеринбурга', kzn: 'Казани', nsk: 'Новосибирска', sam: 'Самары', chel: 'Челябинска', ufa: 'Уфы', rnd: 'Ростова-на-Дону', vrn: 'Воронежа' };
export async function generateMetadata({ params }) {
  const { city } = await params;
  const categories = await getCategories(city);
  const hasIndexableCategories = categories.some((category) => category.slug !== 'other' && category.count > 0);
  const g = G[city] || 'Москвы';
  return {
    title: `Категории препаратов в аптеках ${g} — АптекаА`,
    description: `Все категории лекарственных препаратов, доступные в аптеках ${g}: обезболивающие, от простуды, витамины, антибиотики и другие.`,
    alternates: { canonical: `https://aptekaa.ru/${city}/kategorii` },
    robots: !hasIndexableCategories ? { index: false, follow: true } : undefined,
  };
}
export default async function Page({ params }) {
  const { city } = await params;
  const categories = await getCategories(city);
  const graph = categoryListJsonLd(city);
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(graph) }} />
      <CategoriesClient initialCategories={categories} />
    </>
  );
}
