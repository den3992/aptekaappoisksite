// SEO meta-tag helper: produces Helmet props for the various pages.
// Backend SSR already emits canonical HTML for crawlers; this helper keeps the
// SPA's title/description in sync for users and bookmark previews.
const HOST = (typeof window !== 'undefined' && window.location.origin) || 'https://aptekaa.ru';
const CANONICAL_HOST = 'https://aptekaa.ru';

const cnGenitive = (city) => (city === 'msk' ? 'Москвы' : 'Санкт-Петербурга');
const cnPrepositional = (city) => (city === 'msk' ? 'Москве' : 'Санкт-Петербурге');

export function homeSEO(city = 'msk') {
  const title = `Аптечная справочная ${cnGenitive(city)}: поиск лекарств, цены и наличие в аптеках | АптекаА`;
  const description = `Бесплатная аптечная справочная ${cnGenitive(city)}: цены и наличие лекарств в аптеках, аналоги препаратов, адреса и режим работы. Без регистрации.`;
  return {
    title,
    description,
    canonical: `${CANONICAL_HOST}/${city}`,
  };
}

function pluralPreparat(n) {
  const n10 = n % 10, n100 = n % 100;
  if (n100 >= 11 && n100 <= 14) return 'препаратов';
  if (n10 === 1) return 'препарат';
  if (n10 >= 2 && n10 <= 4) return 'препарата';
  return 'препаратов';
}

export function categorySEO(city, cat, count) {
  const g = cnGenitive(city);
  let title, description;
  if (count && count > 0) {
    const pl = pluralPreparat(count);
    title = `${cat.title} — купить в аптеках ${g}, ${count} ${pl} | АптекаА`;
    description = `${cat.title} — ${count} ${pl} в аптеках ${g}. Сравните цены и наличие, подберите аналоги по действующему веществу. Бесплатно, без регистрации.`;
  } else {
    title = `${cat.title} — купить в аптеках ${g} | АптекаА`;
    description = `${cat.title} в аптеках ${g}. Сравните цены и наличие, подберите аналоги по действующему веществу. Бесплатно, без регистрации.`;
  }
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
  const title = `${ph.name} — адрес, телефон, режим работы | АптекаА`;
  const description = (
    `${ph.name} в ${cnPrepositional(city)}: ${ph.address}. Телефон ${ph.phone || ''}. ` +
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
