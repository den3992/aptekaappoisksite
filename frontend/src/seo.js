// SEO meta-tag helper: produces Helmet props for the various pages.
// Backend SSR already emits canonical HTML for crawlers; this helper keeps the
// SPA's title/description in sync for users and bookmark previews.
const HOST = (typeof window !== 'undefined' && window.location.origin) || 'https://aptekaa.ru';
const CANONICAL_HOST = 'https://aptekaa.ru';

const cnGenitive = (city) => (city === 'msk' ? 'Москвы' : 'Санкт-Петербурга');
const cnPrepositional = (city) => (city === 'msk' ? 'Москве' : 'Санкт-Петербурге');
const cnNomin = (city) => (city === 'msk' ? 'Москва' : 'Санкт-Петербург');

export function homeSEO(city = 'msk') {
  const title = `АптекаА — поиск лекарств и сравнение цен в аптеках ${cnGenitive(city)}`;
  const description = `Бесплатный агрегатор цен и наличия лекарств в аптеках ${cnGenitive(city)}. Сравнивайте цены, ищите аналоги, находите ближайшие аптеки.`;
  return {
    title,
    description,
    canonical: `${CANONICAL_HOST}/${city}`,
  };
}

export function categorySEO(city, cat) {
  const title = `${cat.title} — препараты в аптеках ${cnGenitive(city)} | АптекаА`;
  const description = `Каталог категории «${cat.title}» в аптеках ${cnGenitive(city)}. Сравните цены и наличие препаратов.`;
  return {
    title,
    description,
    canonical: `${CANONICAL_HOST}/${city}/kategorii/${cat.slug}`,
  };
}

export function medSEO(city, med) {
  const parts = [med.name];
  if (med.dosage) parts.push(med.dosage);
  parts.push(`купить в ${cnPrepositional(city)} — цены и наличие в аптеках | АптекаА`);
  const title = parts.join(' ');
  const enrichedSummary = med.enrichment?.summary;
  const description = (
    enrichedSummary
      ? `${enrichedSummary} Сравните цены и наличие в аптеках ${cnGenitive(city)}.`
      : (
        `Сравните цены на ${med.name}` +
        (med.mnn ? ` (${med.mnn.toLowerCase()})` : '') +
        (med.form ? `, ${med.form.toLowerCase()}` : '') +
        (med.dosage ? `, ${med.dosage}` : '') +
        ` в аптеках ${cnGenitive(city)}. Аналоги, наличие, адреса. ` +
        (med.rx ? 'Отпускается по рецепту. ' : '') +
        'Бесплатный поиск.'
      )
  ).slice(0, 300);
  return {
    title,
    description,
    canonical: `${CANONICAL_HOST}/${city}/preparaty/${med.slug}`,
  };
}

export function pharmacySEO(city, ph) {
  const cn = cnNomin(city);
  const title = `${ph.name} — адрес, телефон, режим работы | АптекаА`;
  const description = (
    `${ph.name} в ${cn}: ${ph.address}. Телефон ${ph.phone || ''}. ` +
    `Режим работы: ${ph.hours || ''}. Сравните наличие и цены лекарств.`
  ).slice(0, 300);
  return {
    title,
    description,
    canonical: `${CANONICAL_HOST}/${city}/apteki/${ph.id}`,
  };
}

export function searchSEO(city, q) {
  const title = q
    ? `Поиск «${q}» в аптеках ${cnGenitive(city)} | АптекаА`
    : `Поиск лекарств в аптеках ${cnGenitive(city)} | АптекаА`;
  return {
    title,
    description: `Поиск лекарств в аптеках ${cnGenitive(city)}.`,
    canonical: `${CANONICAL_HOST}/${city}/poisk${q ? `?q=${encodeURIComponent(q)}` : ''}`,
  };
}

export function pageNotFoundSEO() {
  return {
    title: 'Страница не найдена | АптекаА',
    description: 'Запрошенная страница не найдена.',
    canonical: `${CANONICAL_HOST}/`,
  };
}
