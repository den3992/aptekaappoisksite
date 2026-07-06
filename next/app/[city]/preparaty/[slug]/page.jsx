// Server Component обёртка над MedDetailClient.
// - generateMetadata: title/description/canonical/og из данных препарата.
// - JSON-LD @graph (Drug + Product + MedicalWebPage + BreadcrumbList)
//   рендерится в HTML на стороне сервера → Яндекс/Google видят его сразу,
//   без необходимости выполнять JS.
// Клиент-компонент сам перерисовывает интерактив.
import MedDetailClient from './MedDetailClient';
import { medMetadata, medGraphJsonLd } from '../../../../lib/schemas';
import { fetchMed, fetchCategories } from '../../../../api/client';
import { notFound } from 'next/navigation';

export async function generateMetadata({ params }) {
  const { city, slug } = await params;
  try {
    const med = await fetchMed(slug, city);
    const meta = medMetadata(city, med);
    // Динамический noindex для тупиковых страниц: нет реальной цены И нет
    // аналогов по МНН (seo.py, commit 6303b81 — потеряно при миграции на Next,
    // восстановлено в audit #3). ~1099 страниц. Sitemap их и так исключает;
    // meta noindex не даёт им попасть в индекс по внутренним ссылкам.
    // Индексируем гео-страницу ТОЛЬКО при реальном наличии в ЭТОМ городе.
    // Пустые (нет в наличии в данном городе) Яндекс всё равно бракует как
    // «малоценные» — noindex концентрирует бюджет обхода на ценных страницах.
    const cityPrices = Array.isArray(med?.prices_by_city?.[city]) ? med.prices_by_city[city] : [];
    const _nets = new Set(cityPrices.filter((p) => p && p.price > 0).map((p) => p.pharmacy_id));
    if (_nets.size < 2) {
      meta.robots = { index: false, follow: true };  // индексируем только страницы со сравнением (>=2 сетей)
    }
    return meta;
  } catch (e) {
    return {};
  }
}

export default async function Page({ params }) {
  const { city, slug } = await params;
  let med = null;
  try {
    med = await fetchMed(slug, city);
  } catch (e) {
    /* fall through to notFound */
  }
  if (!med) notFound();
  // categories отдаём в SSR-проп, чтобы название категории в лиде и хлебных
  // крошках совпало сервер↔клиент (иначе hydration mismatch, React #418, и
  // бот видит SSR без категорийной перелинковки). fetchCategories кэширован.
  const categories = await fetchCategories().catch(() => []);
  const graph = medGraphJsonLd(city, med);
  return (
    <>
      {graph && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(graph) }}
        />
      )}
      <MedDetailClient initialMed={med} initialCategories={categories} />
    </>
  );
}
