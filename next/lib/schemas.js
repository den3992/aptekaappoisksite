// Сборщики schema.org @graph для Next.js SSR — портированы из seo.py
// (render_medication_for_bot / render_pharmacy_for_bot).

import { categoryContent } from './categoryContent';
import { formatName } from '../utils/text';

const HOST = 'https://aptekaa.ru';

const CN_GEN = { msk: 'Москвы', spb: 'Санкт-Петербурга', krd: 'Краснодара', nn: 'Нижнего Новгорода', ekb: 'Екатеринбурга', kzn: 'Казани', nsk: 'Новосибирска', sam: 'Самары', chel: 'Челябинска', ufa: 'Уфы' };
const CN_LOC = { msk: 'Москве', spb: 'Санкт-Петербурге', krd: 'Краснодаре', nn: 'Нижнем Новгороде', ekb: 'Екатеринбурге', kzn: 'Казани', nsk: 'Новосибирске', sam: 'Самаре', chel: 'Челябинске', ufa: 'Уфе' };
const CN_NOM = { msk: 'Москва', spb: 'Санкт-Петербург', krd: 'Краснодар', nn: 'Нижний Новгород', ekb: 'Екатеринбург', kzn: 'Казань', nsk: 'Новосибирск', sam: 'Самара', chel: 'Челябинск', ufa: 'Уфа' };
const cnGen = (city) => CN_GEN[city] || CN_GEN.msk;
const cnLoc = (city) => CN_LOC[city] || CN_LOC.msk;

function titleCase(s) {
  if (!s) return '';
  const t = String(s).trim();
  return t.charAt(0).toUpperCase() + t.slice(1).toLowerCase();
}

// Вопрос-ответ для FAQPage (JSON-LD) И видимого блока на странице препарата —
// контент один и тот же (требование Яндекса: разметка = видимый текст).
export function medFaqItems(city, med) {
  if (!med) return [];
  const loc = cnLoc(city);
  const gen = cnGen(city);
  const name = formatName(med.name);
  const arr = (med.prices_by_city && med.prices_by_city[city]) || [];
  const prices = arr.map((o) => o && o.price).filter((p) => typeof p === 'number');
  const nets = new Set(arr.map((o) => o && o.pharmacy_id).filter(Boolean));
  const items = [];
  if (prices.length) {
    const low = Math.min(...prices);
    const high = Math.max(...prices);
    const priceStr = low === high ? `${low} ₽` : `от ${low} до ${high} ₽`;
    items.push({
      q: `Сколько стоит ${name} в ${loc}?`,
      a: `Цена ${name} в аптеках ${gen} — ${priceStr}. Актуальные цены и наличие в конкретных аптеках показаны на карте на этой странице.`,
    });
  }
  const netNames = [];
  if (nets.has('gorzdrav')) netNames.push('Горздрав');
  if (nets.has('apteka366')) netNames.push('Аптека 36,6');
  if (netNames.length) {
    items.push({
      q: `Где купить ${name} в ${loc}?`,
      a: `${name} есть в наличии в аптеках ${netNames.length > 1 ? `сетей ${netNames.join(' и ')}` : `сети ${netNames[0]}`} в ${loc}. Аптеки с этим препаратом отмечены на карте — выберите ближайшую и постройте маршрут.`,
    });
  }
  if (med.mnn) {
    items.push({
      q: `Какие аналоги у ${name}?`,
      a: `Аналоги ${name} по действующему веществу (${med.mnn.toLowerCase()}) перечислены в разделе «Аналоги по МНН» на этой странице — с ценами и наличием в ${loc}.`,
    });
  }
  items.push({
    q: `${name} отпускается по рецепту?`,
    a: med.rx
      ? `Да, ${name} отпускается по рецепту врача.`
      : `Нет, ${name} отпускается без рецепта.`,
  });
  return items;
}

export function medMetadata(city, med) {
  if (!med) return {};
  // Кол-во аптечных сетей с ценой в городе → условная формулировка:
  // «сравните цены» честно показываем только когда сетей >=2.
  const _arr = (med.prices_by_city && med.prices_by_city[city]) || [];
  const _nets = new Set(_arr.map((o) => o && o.pharmacy_id).filter(Boolean));
  const _multi = _nets.size >= 2;
  // Реальные сети препарата в городе — для честного перечисления в мете
  // (city-точно: в krd/nn это не Горздрав/36,6, а свои сети).
  const _NET_LABELS = { gorzdrav: 'Горздрав', apteka366: 'Аптека 36,6', rigla: 'Ригла', maksavit: 'Максавит', aptechestvo: 'Аптечество', zdorovie: 'Здоровье', magnit: 'Магнит Аптека' };
  const _netNames = [..._nets].map((id) => _NET_LABELS[id]).filter(Boolean);
  const _netStr = _netNames.length <= 3
    ? _netNames.slice(0, -1).join(', ') + ' и ' + _netNames.slice(-1)
    : _netNames.slice(0, 2).join(', ') + ' и других';
  const _hasPrice = _arr.length > 0;
  const name = formatName(med.name);
  const parts = [name];
  if (med.dosage) parts.push(med.dosage);
  parts.push(
    _multi
      ? `купить в ${cnLoc(city)} — сравните цены в аптеках | АптекаА`
      : _hasPrice
        ? `купить в ${cnLoc(city)} — цена и наличие в аптеках | АптекаА`
        : `в ${cnLoc(city)} — аналоги и наличие в аптеках | АптекаА`,
  );
  const title = parts.join(' ');
  const _ingr =
    (med.mnn ? ` (${med.mnn.toLowerCase()})` : '') +
    (med.form ? `, ${med.form.toLowerCase()}` : '') +
    (med.dosage ? `, ${med.dosage}` : '');
  const _lead = _multi
    ? `Сравните цены на ${name}${_ingr} в сетях ${_netStr}`
    : _hasPrice
      ? `Узнайте цену и наличие ${name}${_ingr}`
      : `${name}${_ingr}: аналоги и наличие`;
  const description = (
    `${_lead} в аптеках ${cnGen(city)}. Аналоги, наличие, адреса на карте. ` +
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
  const name = formatName(med.name);

  const drug = {
    '@type': 'Drug',
    '@id': `${canonical}#drug`,
    name: name,
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
    name: [name, med.dosage].filter(Boolean).join(' '),
    brand: med.manufacturer ? { '@type': 'Brand', name: med.manufacturer } : undefined,
    description: drug.name,
    image,
    url: canonical,
    category: 'Лекарственные препараты',
    isRelatedTo: { '@id': `${canonical}#drug` },
  };
  Object.keys(product).forEach(k => product[k] === undefined && delete product[k]);

  // AggregateOffer — ценовой rich-сниппет в Яндексе. Цены из всех сетей города
  // (Горздрав + Аптека 36,6), по всем упаковкам.
  const _offerPrices = ((med.prices_by_city && med.prices_by_city[city]) || [])
    .map((o) => o && o.price)
    .filter((p) => typeof p === 'number');
  if (_offerPrices.length) {
    product.offers = {
      '@type': 'AggregateOffer',
      priceCurrency: 'RUB',
      lowPrice: Math.min(..._offerPrices),
      highPrice: Math.max(..._offerPrices),
      offerCount: _offerPrices.length,
      availability: 'https://schema.org/InStock',
    };
  }

  const medweb = {
    '@type': 'MedicalWebPage',
    '@id': `${canonical}#webpage`,
    url: canonical,
    name: `${name} ${med.dosage || ''}`.trim(),
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
      { '@type': 'ListItem', position: 3, name: name, item: canonical },
    ],
  };

  const _faqItems = medFaqItems(city, med);
  const faq = _faqItems.length
    ? {
        '@type': 'FAQPage',
        '@id': `${canonical}#faq`,
        mainEntity: _faqItems.map((it) => ({
          '@type': 'Question',
          name: it.q,
          acceptedAnswer: { '@type': 'Answer', text: it.a },
        })),
      }
    : null;

  return {
    '@context': 'https://schema.org',
    '@graph': [medweb, drug, product, breadcrumbs, ...(faq ? [faq] : [])],
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
      addressLocality: CN_NOM[city] || CN_NOM.msk,
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

// FAQPage для страницы категории (видимый блок = эта же разметка).
export function categoryFaqJsonLd(city, cat) {
  if (!cat) return null;
  const c = categoryContent(cat.slug, city);
  if (!c || !c.faq.length) return null;
  return {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: c.faq.map((qa) => ({
      '@type': 'Question',
      name: qa.q,
      acceptedAnswer: { '@type': 'Answer', text: qa.a },
    })),
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
