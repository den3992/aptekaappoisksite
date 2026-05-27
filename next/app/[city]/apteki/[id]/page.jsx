import PharmacyDetailClient from './PharmacyDetailClient';
import { fetchPharmacy } from '../../../../api/client';
import { pharmacyJsonLd } from '../../../../lib/schemas';
const L = { msk: 'Москве', spb: 'Санкт-Петербурге' };
export async function generateMetadata({ params }) {
  const { city, id } = await params;
  const loc = L[city] || 'Москве';
  let ph = null;
  try { ph = await fetchPharmacy(id); } catch (e) { /* ignore */ }
  if (!ph) return { title: `Аптека не найдена в ${loc} — АптекаА` };
  return {
    title: `${ph.name} в ${loc} — адрес, телефон, режим работы — АптекаА`,
    description: `${ph.name} в ${loc}: ${ph.address || ''}. ${ph.phone || ''}. ${ph.hours || ''}. Сравните наличие и цены лекарств.`.slice(0, 300),
    alternates: { canonical: `https://aptekaa.ru/${city}/apteki/${id}` },
  };
}
export default async function Page({ params }) {
  const { city, id } = await params;
  let ph = null;
  try { ph = await fetchPharmacy(id); } catch (e) { /* ignore */ }
  const jsonLd = pharmacyJsonLd(city, ph);
  return (
    <>
      {jsonLd && (
        <script type="application/ld+json" dangerouslySetInnerHTML={{__html: JSON.stringify(jsonLd)}} />
      )}
      <PharmacyDetailClient initialPh={ph} />
    </>
  );
}
