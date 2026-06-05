import CategoryDetailClient from './CategoryDetailClient';
import { fetchCategories } from '../../../../api/client';
import { categoryDetailJsonLd, categoryFaqJsonLd } from '../../../../lib/schemas';
const G = { msk: 'Москвы', spb: 'Санкт-Петербурга', krd: 'Краснодара', nn: 'Нижнего Новгорода', ekb: 'Екатеринбурга', kzn: 'Казани', nsk: 'Новосибирска', sam: 'Самары', chel: 'Челябинска', ufa: 'Уфы' };
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
export default async function Page({ params }) {
  const { city, slug } = await params;
  let cat = null;
  try {
    const all = await fetchCategories();
    cat = all.find(c => c.slug === slug);
  } catch (e) { /* ignore */ }
  const graph = cat ? categoryDetailJsonLd(city, cat) : null;
  const faqGraph = cat ? categoryFaqJsonLd(city, cat) : null;
  return (
    <>
      {graph && (
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(graph) }} />
      )}
      {faqGraph && (
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(faqGraph) }} />
      )}
      <CategoryDetailClient initialCat={cat} />
    </>
  );
}
