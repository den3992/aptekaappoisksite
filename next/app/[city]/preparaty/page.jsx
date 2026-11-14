import CatalogClient from './CatalogClient';
import { getCatalog } from '../../../lib/catalogData';
export const dynamic = 'force-dynamic';
const G = { msk: 'Москвы', spb: 'Санкт-Петербурга', krd: 'Краснодара', nn: 'Нижнего Новгорода', ekb: 'Екатеринбурга', kzn: 'Казани', nsk: 'Новосибирска', sam: 'Самары', chel: 'Челябинска', ufa: 'Уфы', rnd: 'Ростова-на-Дону', vrn: 'Воронежа' };
export async function generateMetadata({ params, searchParams }) {
  const { city } = await params;
  const query = await searchParams;
  const page = Math.max(1, Number.parseInt(query?.page || '1', 10) || 1);
  const result = await getCatalog(city, page);
  const hasIndexableMeds = result.total > 0;
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
  const initialData = await getCatalog(city, page);
  return <CatalogClient initialData={initialData} initialPage={page} />;
}
