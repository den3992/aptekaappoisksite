// Server Component обёртка для главной — добавляет WebSite + Organization
// JSON-LD в HTML на сервере, плюс per-route canonical (layout его не ставит,
// чтобы вложенные роуты могли задать свой).
import HomeClient from './HomeClient';
import { homeJsonLd } from '../../lib/schemas';
import { getCategories, getPopularMeds } from '../../lib/catalogData';
export const dynamic = 'force-dynamic';

export async function generateMetadata({ params }) {
  const { city } = await params;
  return {
    alternates: { canonical: `https://aptekaa.ru/${city}` },
  };
}

export default async function Page({ params }) {
  const { city } = await params;
  const graph = homeJsonLd(city);
  const [categories, popularMeds] = await Promise.all([
    getCategories(city),
    // Popular links are optional; a failed lookup can still retry in the
    // browser without turning a category outage into a false empty catalogue.
    getPopularMeds(city).catch(() => null),
  ]);
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(graph) }}
      />
      <HomeClient initialCategories={categories} initialPopularMeds={popularMeds} />
    </>
  );
}
