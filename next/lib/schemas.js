// Сборщики schema.org @graph для Next.js SSR — портированы из seo.py
// (render_medication_for_bot / render_pharmacy_for_bot).

import { categoryContent } from './categoryContent';
import { formatName, formatManufacturer } from '../utils/text';

const HOST = 'https://aptekaa.ru';

const CN_GEN = { msk: 'Москвы', spb: 'Санкт-Петербурга', krd: 'Краснодара', nn: 'Нижнего Новгорода', ekb: 'Екатеринбурга', kzn: 'Казани', nsk: 'Новосибирска', sam: 'Самары', chel: 'Челябинска', ufa: 'Уфы', rnd: 'Ростова-на-Дону', vrn: 'Воронежа' };
const CN_LOC = { msk: 'Москве', spb: 'Санкт-Петербурге', krd: 'Краснодаре', nn: 'Нижнем Новгороде', ekb: 'Екатеринбурге', kzn: 'Казани', nsk: 'Новосибирске', sam: 'Самаре', chel: 'Челябинске', ufa: 'Уфе', rnd: 'Ростове-на-Дону', vrn: 'Воронеже' };
const CN_NOM = { msk: 'Москва', spb: 'Санкт-Петербург', krd: 'Краснодар', nn: 'Нижний Новгород', ekb: 'Екатеринбург', kzn: 'Казань', nsk: 'Новосибирск', sam: 'Самара', chel: 'Челябинск', ufa: 'Уфа', rnd: 'Ростов-на-Дону', vrn: 'Воронеж' };
const cnGen = (city) => CN_GEN[city] || CN_GEN.msk;
const cnLoc = (city) => CN_LOC[city] || CN_LOC.msk;
const isConfirmedOffer = (offer) => offer?.availability_confirmed === true;
const observedDate = (value) => {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'Europe/Moscow',
  }).format(date);
};

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
  const nameDose = [name, med.dosage].filter(Boolean).join(' ');
  const arr = (med.prices_by_city && med.prices_by_city[city]) || [];
  const confirmed = arr.filter(isConfirmedOffer);
  const historical = arr.filter((offer) => !isConfirmedOffer(offer));
  const historicalLatest = Object.values(historical.reduce((acc, offer) => {
    const key = offer?.pharmacy_id || 'source';
    if (!acc[key] || String(offer?.observed_at || '') > String(acc[key]?.observed_at || '')) acc[key] = offer;
    return acc;
  }, {}));
  const prices = confirmed.map((o) => o && o.price).filter((p) => typeof p === 'number');
  const historicalPrices = historicalLatest.map((o) => o && o.price).filter((p) => typeof p === 'number');
  const nets = new Set(confirmed.map((o) => o && o.pharmacy_id).filter(Boolean));
  const items = [];
  if (med.mnn) {
    items.push({
      q: `Какое действующее вещество у ${nameDose}?`,
      a: `Действующее вещество (МНН) — ${titleCase(med.mnn)}. Форма выпуска: ${(med.form || '').toLowerCase()}${med.dosage ? `, дозировка ${med.dosage}` : ''}.`,
    });
  }
  const packs = [...new Set((med.variants || []).map((v) => v && v.pack_size).filter(Boolean))];
  if (med.manufacturer || packs.length) {
    const details = [];
    if (med.manufacturer) details.push(`производитель — ${formatManufacturer(med.manufacturer)}`);
    if (packs.length) details.push(`варианты упаковки: ${packs.join(', ')}`);
    items.push({
      q: `Кто производит ${nameDose} и в какой упаковке он выпускается?`,
      a: `${nameDose}: ${details.join('; ')}. Перед покупкой сверяйте дозировку, форму выпуска, производителя и маркировку на конкретной упаковке.`,
    });
  }
  if (prices.length) {
    const low = Math.min(...prices);
    const high = Math.max(...prices);
    const priceStr = low === high ? `${low} ₽` : `от ${low} до ${high} ₽`;
    items.push({
      q: `Сколько стоит ${name} в ${loc}?`,
      a: `Цена ${name} в аптеках ${gen} — ${priceStr}. Актуальные цены и наличие в конкретных аптеках показаны на карте на этой странице.`,
    });
  }
  if (!prices.length) {
    if (historicalPrices.length) {
      const low = Math.min(...historicalPrices);
      const latest = historicalLatest
        .filter((offer) => offer?.price === low)
        .map((offer) => offer?.observed_at)
        .filter(Boolean)
        .sort()
        .at(-1);
      items.push({
        q: `Какая последняя зафиксированная цена ${nameDose} в ${loc}?`,
        a: `Последняя зафиксированная цена — ${low} ₽${observedDate(latest) ? ` по данным на ${observedDate(latest)}` : ''}. Это справочная историческая цена: текущее наличие и стоимость необходимо уточнить в аптеке.`,
      });
    } else {
      items.push({
        q: `Где проверить цену и наличие ${nameDose} в ${loc}?`,
        a: `На этой странице АптекаА показывает только проверенные данные аптечных сетей ${gen}. Если цены нет, актуальное предложение еще не получено; неподтвержденные наличие и стоимость мы не публикуем.`,
      });
    }
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
      a: `Раздел «Аналоги по МНН» показывает препараты с тем же действующим веществом (${med.mnn.toLowerCase()}) и сопоставимой лекарственной формой, если они есть в каталоге. Цену и наличие проверяйте на странице конкретного аналога.`,
    });
  }
  if (med.rx === true) {
    items.push({ q: `${nameDose} отпускается по рецепту?`, a: `Да, ${nameDose} относится к рецептурным препаратам. Для госпитальных форм применение возможно только медицинским персоналом.` });
  } else if (med.rx === false) {
    items.push({ q: `${nameDose} отпускается по рецепту?`, a: `${nameDose} отпускается без рецепта, если иное не указано в инструкции конкретной упаковки. Перед применением проконсультируйтесь со специалистом.` });
  } else {
    items.push({ q: `${nameDose} отпускается по рецепту?`, a: `Режим отпуска необходимо уточнить по официальной инструкции и маркировке конкретной упаковки ${nameDose}.` });
  }
  return items;
}

export function medMetadata(city, med) {
  if (!med) return {};
  // Кол-во аптечных сетей с ценой в городе → условная формулировка:
  // «сравните цены» честно показываем только когда сетей >=2.
  const _arr = (med.prices_by_city && med.prices_by_city[city]) || [];
  // Реальные сети препарата в городе — для честного перечисления в мете
  // (city-точно: в krd/nn это не Горздрав/36,6, а свои сети).
  const _NET_LABELS = { gorzdrav: 'Горздрав', apteka366: 'Аптека 36,6', rigla: 'Ригла', rigla_archive: 'Ригла', maksavit: 'Максавит', aptechestvo: 'Аптечество', zdorovie: 'Здоровье', magnit: 'Магнит Аптека', farmakopeika: 'Фармакопейка' };
  const _confirmed = _arr.filter(isConfirmedOffer);
  const _historical = _arr.filter((offer) => !isConfirmedOffer(offer));
  const _historicalLatest = Object.values(_historical.reduce((acc, offer) => {
    const key = offer?.pharmacy_id || 'source';
    if (!acc[key] || String(offer?.observed_at || '') > String(acc[key]?.observed_at || '')) acc[key] = offer;
    return acc;
  }, {}));
  const _nets = new Set(_confirmed.map((o) => o && o.pharmacy_id).filter((id) => _NET_LABELS[id]));
  const _multi = _nets.size >= 2;
  const _netNames = [..._nets].map((id) => _NET_LABELS[id]).filter(Boolean);
  const _netStr = _netNames.length <= 1
    ? (_netNames[0] || '')
    : _netNames.length <= 3
      ? `${_netNames.slice(0, -1).join(', ')} и ${_netNames.at(-1)}`
      : `${_netNames.slice(0, 2).join(', ')} и других`;
  const _hasPrice = _confirmed.some((offer) => typeof offer?.price === 'number');
  const _historicalPrices = _historicalLatest.map((offer) => offer?.price).filter((price) => typeof price === 'number');
  const _hasHistoricalPrice = _historicalPrices.length > 0;
  const name = formatName(med.name);
  const manufacturer = formatManufacturer(med.manufacturer);
  const titleQualifier = med.seo?.title_qualifier
    ? ` ${formatManufacturer(med.seo.title_qualifier)}`
    : '';
  const packs = [...new Set((med.variants || []).map((v) => v && v.pack_size).filter(Boolean))];
  const packText = packs.slice(0, 2).join(', ');
  const nameDose = [name, med.dosage].filter(Boolean).join(' ');
  const title = _multi
    ? `${nameDose}${titleQualifier} — сравнить цены в ${cnLoc(city)} | АптекаА`
    : _hasPrice
      ? `${nameDose}${titleQualifier} купить в ${cnLoc(city)} — цена и наличие | АптекаА`
      : _hasHistoricalPrice
        ? `${nameDose}${titleQualifier} в ${cnLoc(city)} — последняя цена | АптекаА`
      : `${nameDose}${titleQualifier} — проверка наличия и аналоги в ${cnLoc(city)} | АптекаА`;
  const availability = _multi
    ? `сравнение цен в сетях ${_netStr}`
    : _hasPrice
      ? 'актуальная цена и подтвержденное наличие'
      : _hasHistoricalPrice
        ? `последняя зафиксированная цена ${Math.min(..._historicalPrices)} ₽; текущее наличие уточняйте`
      : 'проверка наличия и аналоги';
  const makeDescription = (facts) => (
    `${nameDose}${facts ? ` — ${facts}` : ''}. ` +
    `${availability.charAt(0).toUpperCase() + availability.slice(1)} в ${cnLoc(city)}. ` +
    'Форма выпуска и справочные сведения. Только подтвержденные предложения аптек.'
  );
  let productFacts = [manufacturer, packText ? `упаковки ${packText}` : ''].filter(Boolean).join(', ');
  let description = makeDescription(productFacts);
  if (description.length > 190 && packText) {
    productFacts = manufacturer;
    description = makeDescription(productFacts);
  }
  if (description.length > 190) description = makeDescription('');
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
    prescriptionStatus: med.rx === true ? 'PrescriptionOnly' : med.rx === false ? 'OTC' : undefined,
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
    brand: { '@type': 'Brand', name },
    manufacturer: med.manufacturer ? { '@type': 'Organization', name: med.manufacturer } : undefined,
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
    .filter(isConfirmedOffer)
    .map((o) => o && o.price)
    .filter((p) => typeof p === 'number');
  if (_offerPrices.length) {
    product.offers = {
      '@type': 'AggregateOffer',
      priceCurrency: 'RUB',
      lowPrice: Math.min(..._offerPrices),
      highPrice: Math.max(..._offerPrices),
      offerCount: _offerPrices.length,
    };
  }

  // AggregateRating + Review — звёзды отзывов в выдаче. ТОЛЬКО при наличии
  // реальных опубликованных отзывов (разметка = видимый блок, требование
  // Яндекса). Никнейм не собираем → автор обобщённый. Отзывы — на канонический
  // препарат, поэтому одинаковы во всех городах (это норма для UGC о товаре).
  const _rv = med.reviews;
  if (_rv && _rv.count >= 1 && _rv.avg >= 1) {
    product.aggregateRating = {
      '@type': 'AggregateRating',
      ratingValue: _rv.avg,
      reviewCount: _rv.count,
      bestRating: 5,
      worstRating: 1,
    };
    const _items = Array.isArray(_rv.items) ? _rv.items : [];
    if (_items.length) {
      product.review = _items.map((r) => {
        const rev = {
          '@type': 'Review',
          author: { '@type': 'Person', name: 'Посетитель сайта' },
          reviewRating: { '@type': 'Rating', ratingValue: r.rating, bestRating: 5, worstRating: 1 },
          reviewBody: r.text,
        };
        if (r.created_at) {
          try { rev.datePublished = new Date(r.created_at).toISOString().slice(0, 10); } catch (e) { /* ignore */ }
        }
        return rev;
      });
      // Фото из отзывов — дополнительные изображения товара (image-выдача).
      const _photoUrls = _items.flatMap((r) => (Array.isArray(r.photos) ? r.photos : [])
        .map((p) => (p && p.startsWith('http') ? p : `${HOST}${p}`)));
      if (_photoUrls.length) {
        const _base = product.image ? (Array.isArray(product.image) ? product.image : [product.image]) : [];
        product.image = [..._base, ..._photoUrls];
      }
    }
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
        legalName: 'Индивидуальный предприниматель Егорова Анастасия Васильевна',
        url: HOST,
        logo: `${HOST}/icon-512.png`,
        email: 'info@aptekaa.ru',
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
          legalName: 'Индивидуальный предприниматель Егорова Анастасия Васильевна',
          url: HOST,
          logo: `${HOST}/icon-512.png`,
          email: 'info@aptekaa.ru',
        },
      },
    ],
  };
}
