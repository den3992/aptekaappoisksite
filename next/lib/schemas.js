// Сборщики schema.org @graph для Next.js SSR — портированы из seo.py
// (render_medication_for_bot / render_pharmacy_for_bot).

const HOST = 'https://aptekaa.ru';

const cnGen = (city) => (city === 'msk' ? 'Москвы' : 'Санкт-Петербурга');
const cnLoc = (city) => (city === 'msk' ? 'Москве' : 'Санкт-Петербурге');

function titleCase(s) {
  if (!s) return '';
  const t = String(s).trim();
  return t.charAt(0).toUpperCase() + t.slice(1).toLowerCase();
}

export function medMetadata(city, med) {
  if (!med) return {};
  const parts = [med.name];
  if (med.dosage) parts.push(med.dosage);
  parts.push(`купить в ${cnLoc(city)} — цены и наличие в аптеках | АптекаА`);
  const title = parts.join(' ');
  const description = (
    `Сравните цены на ${med.name}` +
    (med.mnn ? ` (${med.mnn.toLowerCase()})` : '') +
    (med.form ? `, ${med.form.toLowerCase()}` : '') +
    (med.dosage ? `, ${med.dosage}` : '') +
    ` в аптеках ${cnGen(city)}. Аналоги, наличие, адреса. ` +
    (med.rx ? 'Отпускается по рецепту. ' : '') +
    'Бесплатный поиск.'
  ).slice(0, 300);
  const canonical = `${HOST}/${city}/preparaty/${med.canonical_slug || med.slug}`;
  const image = med.image_url ? `${HOST}${med.image_url}` : undefined;
  return {
    title: { absolute: title },
    description,
    alternates: { canonical },
    openGraph: {
      title,
      description,
      url: canonical,
      type: 'website',
      images: image ? [{ url: image }] : undefined,
    },
  };
}

export function medGraphJsonLd(city, med) {
  if (!med) return null;
  const canonical = `${HOST}/${city}/preparaty/${med.canonical_slug || med.slug}`;
  const image = med.image_url ? `${HOST}${med.image_url}` : undefined;

  const drug = {
    '@type': 'Drug',
    '@id': `${canonical}#drug`,
    name: med.name,
    nonProprietaryName: med.mnn ? titleCase(med.mnn) : undefined,
    activeIngredient: med.mnn ? titleCase(med.mnn) : undefined,
    dosageForm: med.form ? med.form.toLowerCase() : undefined,
    prescriptionStatus: med.rx ? 'PrescriptionOnly' : 'OTC',
    image,
    url: canonical,
    manufacturer: med.manufacturer ? { '@type': 'Organization', name: med.manufacturer } : undefined,
  };
  // Удаляем undefined.
  Object.keys(drug).forEach(k => drug[k] === undefined && delete drug[k]);

  const product = {
    '@type': 'Product',
    '@id': `${canonical}#product`,
    name: [med.name, med.dosage].filter(Boolean).join(' '),
    brand: med.manufacturer ? { '@type': 'Brand', name: med.manufacturer } : undefined,
    description: drug.name,
    image,
    url: canonical,
    category: 'Лекарственные препараты',
    isRelatedTo: { '@id': `${canonical}#drug` },
  };
  Object.keys(product).forEach(k => product[k] === undefined && delete product[k]);

  const medweb = {
    '@type': 'MedicalWebPage',
    '@id': `${canonical}#webpage`,
    url: canonical,
    name: `${med.name} ${med.dosage || ''}`.trim(),
    inLanguage: 'ru',
    audience: { '@type': 'MedicalAudience', audienceType: 'Patient' },
    mainContentOfPage: { '@id': `${canonical}#drug` },
    isPartOf: { '@type': 'WebSite', name: 'АптекаА', url: HOST },
  };
  if (med.prices_updated_at) {
    try {
      medweb.lastReviewed = new Date(med.prices_updated_at).toISOString().slice(0, 10);
    } catch (e) { /* ignore */ }
  }

  const breadcrumbs = {
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Главная', item: `${HOST}/${city}` },
      { '@type': 'ListItem', position: 2, name: 'Препараты', item: `${HOST}/${city}/preparaty` },
      { '@type': 'ListItem', position: 3, name: med.name, item: canonical },
    ],
  };

  return {
    '@context': 'https://schema.org',
    '@graph': [medweb, drug, product, breadcrumbs],
  };
}

export function homeJsonLd(city) {
  const canonical = `${HOST}/${city}`;
  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'WebSite',
        name: 'АптекаА',
        url: canonical,
        potentialAction: {
          '@type': 'SearchAction',
          target: `${canonical}/poisk?q={search_term_string}`,
          'query-input': 'required name=search_term_string',
        },
      },
      {
        '@type': 'Organization',
        name: 'АптекаА',
        legalName: 'ООО «Идеал-Фарм»',
        url: HOST,
        logo: `${HOST}/icon-512.png`,
        email: 'info@aptekaa.ru',
        telephone: '+7-800-700-70-70',
        identifier: [
          { '@type': 'PropertyValue', propertyID: 'ИНН', value: '5050110424' },
          { '@type': 'PropertyValue', propertyID: 'КПП', value: '505001001' },
          { '@type': 'PropertyValue', propertyID: 'ОГРН', value: '1145050001942' },
        ],
        address: {
          '@type': 'PostalAddress',
          streetAddress: 'ул. Садовая, д. 1, пом. II',
          addressLocality: 'Фрязино',
          addressRegion: 'Московская область',
          postalCode: '141195',
          addressCountry: 'RU',
        },
      },
    ],
  };
}

export function pharmacyJsonLd(city, ph) {
  if (!ph) return null;
  return {
    '@context': 'https://schema.org',
    '@type': 'Pharmacy',
    name: ph.name,
    address: {
      '@type': 'PostalAddress',
      streetAddress: ph.address,
      addressLocality: city === 'msk' ? 'Москва' : 'Санкт-Петербург',
      addressCountry: 'RU',
    },
    telephone: ph.phone,
    openingHours: ph.hours,
    geo: ph.lat && ph.lng ? { '@type': 'GeoCoordinates', latitude: ph.lat, longitude: ph.lng } : undefined,
  };
}


// =====================================================================
// Категории (список) и категория-детали
// =====================================================================

export function categoryListJsonLd(city) {
  const url = `${HOST}/${city}/kategorii`;
  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'BreadcrumbList',
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: 'Главная', item: `${HOST}/${city}` },
          { '@type': 'ListItem', position: 2, name: 'Категории', item: url },
        ],
      },
      {
        '@type': 'CollectionPage',
        '@id': `${url}#collection`,
        url,
        name: `Категории препаратов в аптеках ${cnGen(city)}`,
        inLanguage: 'ru',
        isPartOf: { '@type': 'WebSite', name: 'АптекаА', url: HOST },
      },
    ],
  };
}

export function categoryDetailJsonLd(city, cat) {
  if (!cat) return null;
  const url = `${HOST}/${city}/kategorii/${cat.slug}`;
  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'BreadcrumbList',
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: 'Главная', item: `${HOST}/${city}` },
          { '@type': 'ListItem', position: 2, name: 'Категории', item: `${HOST}/${city}/kategorii` },
          { '@type': 'ListItem', position: 3, name: cat.title, item: url },
        ],
      },
      {
        '@type': 'CollectionPage',
        '@id': `${url}#collection`,
        url,
        name: `${cat.title} — препараты в аптеках ${cnGen(city)}`,
        description: `${cat.title} в аптеках ${cnGen(city)}: ${cat.count || 0} препаратов, цены, наличие.`,
        inLanguage: 'ru',
        isPartOf: { '@type': 'WebSite', name: 'АптекаА', url: HOST },
      },
    ],
  };
}

// =====================================================================
// /o-servise
// =====================================================================

export function aboutPageJsonLd() {
  const url = `${HOST}/o-servise`;
  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'BreadcrumbList',
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: 'Главная', item: HOST },
          { '@type': 'ListItem', position: 2, name: 'О сервисе', item: url },
        ],
      },
      {
        '@type': 'AboutPage',
        '@id': `${url}#aboutpage`,
        url,
        name: 'О сервисе АптекаА',
        inLanguage: 'ru',
        isPartOf: { '@type': 'WebSite', name: 'АптекаА', url: HOST },
        mainEntity: {
          '@type': 'Organization',
          name: 'АптекаА',
          legalName: 'ООО «Идеал-Фарм»',
          url: HOST,
          logo: `${HOST}/icon-512.png`,
          email: 'info@aptekaa.ru',
          telephone: '+7-800-700-70-70',
          identifier: [
            { '@type': 'PropertyValue', propertyID: 'ИНН', value: '5050110424' },
            { '@type': 'PropertyValue', propertyID: 'КПП', value: '505001001' },
            { '@type': 'PropertyValue', propertyID: 'ОГРН', value: '1145050001942' },
          ],
          address: {
            '@type': 'PostalAddress',
            streetAddress: 'ул. Садовая, д. 1, пом. II',
            addressLocality: 'Фрязино',
            addressRegion: 'Московская область',
            postalCode: '141195',
            addressCountry: 'RU',
          },
        },
      },
    ],
  };
}
