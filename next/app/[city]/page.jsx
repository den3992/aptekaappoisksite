// Server Component обёртка для главной — добавляет WebSite + Organization
// JSON-LD в HTML на сервере. Интерактивные части (поиск, hero, рамдомные
// trust-badges) рендерит HomeClient.
import HomeClient from './HomeClient';
import { homeJsonLd } from '../../lib/schemas';

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
