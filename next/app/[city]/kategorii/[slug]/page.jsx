import CategoryDetailClient from './CategoryDetailClient';
import { fetchCategories, searchMeds } from '../../../../api/client';
import { categoryDetailJsonLd, categoryFaqJsonLd } from '../../../../lib/schemas';
const G = { msk: 'Москвы', spb: 'Санкт-Петербурга', krd: 'Краснодара', nn: 'Нижнего Новгорода', ekb: 'Екатеринбурга', kzn: 'Казани', nsk: 'Новосибирска', sam: 'Самары', chel: 'Челябинска', ufa: 'Уфы', rnd: 'Ростова-на-Дону', vrn: 'Воронежа' };
const PAGE_SIZE = 24;
export async function generateMetadata({ params, searchParams }) {
  const { city, slug } = await params;
  const query = await searchParams;
  const page = Math.max(1, Number.parseInt(query?.page || '1', 10) || 1);
  const g = G[city] || 'Москвы';
  let cat = null;
  try {
    const all = await fetchCategories(city);
    cat = all.find(c => c.slug === slug);
  } catch (e) { /* ignore */ }
  if (!cat) return { title: `Категория не найдена в аптеках ${g} — АптекаА` };
  return {
    title: `${cat.title} — купить в аптеках ${g}, ${cat.count} препаратов${page > 1 ? `, страница ${page}` : ''} — АптекаА`,
    description: `${cat.title} в аптеках ${g}: ${cat.count} препаратов, цены, наличие, аналоги. Бесплатный поиск без регистрации.`,
    alternates: { canonical: `https://aptekaa.ru/${city}/kategorii/${slug}` },
    robots: cat.count <= 0 || page > 1 ? { index: false, follow: true } : undefined,
  };
}
export default async function Page({ params, searchParams }) {
  const { city, slug } = await params;
  const query = await searchParams;
  const page = Math.max(1, Number.parseInt(query?.page || '1', 10) || 1);
  let cat = null;
  try {
    const all = await fetchCategories(city);
    cat = all.find(c => c.slug === slug);
  } catch (e) { /* ignore */ }
  // Первая страница каталога — СЕРВЕРНО: (1) грид в SSR-HTML -> бот видит
  // ссылки категория->препараты (перелинковка), (2) нет клиентской вставки
  // грида -> CLS ~0 (был 0.47: SEO-блок сдвигался приехавшими карточками).
  let initialData = null;
  try {
    initialData = await searchMeds({ category: slug, city, page, pageSize: PAGE_SIZE });
  } catch (e) { /* клиент дозагрузит сам */ }
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
      <CategoryDetailClient initialCat={cat} initialData={initialData} initialPage={page} />
    </>
  );
}
