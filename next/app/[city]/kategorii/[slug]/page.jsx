import CategoryDetailClient from './CategoryDetailClient';
import { fetchCategories } from '../../../../api/client';
const G = { msk: 'Москвы', spb: 'Санкт-Петербурга' };
export async function generateMetadata({ params }) {
  const { city, slug } = await params;
  const g = G[city] || 'Москвы';
  let cat = null;
  try {
    const all = await fetchCategories();
    cat = all.find(c => c.slug === slug);
  } catch (e) { /* ignore */ }
  if (!cat) return { title: `Категория не найдена в аптеках ${g} — АптекаА` };
  return {
    title: `${cat.title} — купить в аптеках ${g}, ${cat.count} препаратов — АптекаА`,
    description: `${cat.title} в аптеках ${g}: ${cat.count} препаратов, цены, наличие, аналоги. Бесплатный поиск без регистрации.`,
    alternates: { canonical: `https://aptekaa.ru/${city}/kategorii/${slug}` },
  };
}
export default function Page() { return <CategoryDetailClient />; }
