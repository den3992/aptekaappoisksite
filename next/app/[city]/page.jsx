// Server Component обёртка для главной — добавляет WebSite + Organization
// JSON-LD в HTML на сервере, плюс per-route canonical (layout его не ставит,
// чтобы вложенные роуты могли задать свой).
import HomeClient from './HomeClient';
import { homeJsonLd } from '../../lib/schemas';

export async function generateMetadata({ params }) {
  const { city } = await params;
  return {
    alternates: { canonical: `https://aptekaa.ru/${city}` },
  };
}

export default async function Page({ params }) {
  const { city } = await params;
  const graph = homeJsonLd(city);
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(graph) }}
      />
      <HomeClient />
    </>
  );
}
