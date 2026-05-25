// Server Component обёртка над MedDetailClient.
// - generateMetadata: title/description/canonical/og из данных препарата.
// - JSON-LD @graph (Drug + Product + MedicalWebPage + BreadcrumbList)
//   рендерится в HTML на стороне сервера → Яндекс/Google видят его сразу,
//   без необходимости выполнять JS.
// Клиент-компонент сам перерисовывает интерактив.
import MedDetailClient from './MedDetailClient';
import { medMetadata, medGraphJsonLd } from '../../../../lib/schemas';
import { fetchMed } from '../../../../api/client';
import { notFound } from 'next/navigation';

export async function generateMetadata({ params }) {
  const { city, slug } = await params;
  try {
    const med = await fetchMed(slug);
    return medMetadata(city, med);
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
      <MedDetailClient />
    </>
  );
}
