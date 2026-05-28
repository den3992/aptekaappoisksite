// Server Component обёртка над MedDetailClient.
// - generateMetadata: title/description/canonical/og из данных препарата.
// - JSON-LD @graph (Drug + Product + MedicalWebPage + BreadcrumbList)
//   рендерится в HTML на стороне сервера → Яндекс/Google видят его сразу,
//   без необходимости выполнять JS.
// Клиент-компонент сам перерисовывает интерактив.
import MedDetailClient from './MedDetailClient';
import { medMetadata, medGraphJsonLd } from '../../../../lib/schemas';
import { fetchMed, fetchAnalogs } from '../../../../api/client';
import { notFound } from 'next/navigation';

export async function generateMetadata({ params }) {
  const { city, slug } = await params;
  try {
    const med = await fetchMed(slug);
    const meta = medMetadata(city, med);
    // Динамический noindex для тупиковых страниц: нет реальной цены И нет
    // аналогов по МНН (seo.py, commit 6303b81 — потеряно при миграции на Next,
    // восстановлено в audit #3). ~1099 страниц. Sitemap их и так исключает;
    // meta noindex не даёт им попасть в индекс по внутренним ссылкам.
    const hasPrice =
      med?.prices_by_city &&
      Object.values(med.prices_by_city).some(
        (arr) => Array.isArray(arr) && arr.length > 0,
      );
    let hasAnalogs = false;
    if (!hasPrice) {
      try {
        const analogs = await fetchAnalogs(slug, 1);
        hasAnalogs = Array.isArray(analogs) && analogs.length > 0;
      } catch (e) {
        /* при ошибке analogs не трогаем индексацию */
      }
    }
    if (!hasPrice && !hasAnalogs) {
      meta.robots = { index: false, follow: true };
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
    med = await fetchMed(slug);
  } catch (e) {
    /* fall through to notFound */
  }
  if (!med) notFound();
  const graph = medGraphJsonLd(city, med);
  return (
    <>
      {graph && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(graph) }}
        />
      )}
      <MedDetailClient initialMed={med} />
    </>
  );
}
