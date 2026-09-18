import CatalogClient from './CatalogClient';
import { searchMeds } from '../../../api/client';
const G = { msk: 'Москвы', spb: 'Санкт-Петербурга', krd: 'Краснодара', nn: 'Нижнего Новгорода', ekb: 'Екатеринбурга', kzn: 'Казани', nsk: 'Новосибирска', sam: 'Самары', chel: 'Челябинска', ufa: 'Уфы', rnd: 'Ростова-на-Дону', vrn: 'Воронежа' };
const PAGE_SIZE = 48;
export async function generateMetadata({ params, searchParams }) {
  const { city } = await params;
  const query = await searchParams;
  const page = Math.max(1, Number.parseInt(query?.page || '1', 10) || 1);
  let hasIndexableMeds = true;
  try {
    const result = await searchMeds({ city, page: 1, pageSize: 1 });
    hasIndexableMeds = (result?.total || 0) > 0;
  } catch (e) { /* keep the page indexable on a transient backend failure */ }
  const g = G[city] || 'Москвы';
  return {
    title: `Каталог лекарств А–Я в аптеках ${g}${page > 1 ? ` — страница ${page}` : ''} — АптекаА`,
    description: `Полный алфавитный каталог лекарственных препаратов в аптеках ${g}: цены, наличие, аналоги. Бесплатно, без регистрации.`,
    alternates: { canonical: `https://aptekaa.ru/${city}/preparaty` },
    robots: page > 1 || !hasIndexableMeds ? { index: false, follow: true } : undefined,
  };
}
export default async function Page({ params, searchParams }) {
  const { city } = await params;
  const query = await searchParams;
  const page = Math.max(1, Number.parseInt(query?.page || '1', 10) || 1);
  let initialData = null;
  try {
    initialData = await searchMeds({ city, page, pageSize: PAGE_SIZE });
  } catch (e) { /* client can retry */ }
  return <CatalogClient initialData={initialData} initialPage={page} />;
}
