import ForPharmacies from '../../components/ForPharmacies';

export const metadata = {
  title: 'Для аптек — подключение к сервису АптекаА бесплатно',
  description: 'Подключите вашу аптеку или сеть к агрегатору АптекаА — это бесплатно. FTP-выгрузка прайс-листа, отображение цен и наличия в карточках препаратов, привлечение клиентов из Яндекс-поиска.',
  alternates: { canonical: 'https://aptekaa.ru/dlya-aptek' },
};

export default function Page() {
  const jsonLd = {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'BreadcrumbList',
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: 'Главная', item: 'https://aptekaa.ru' },
          { '@type': 'ListItem', position: 2, name: 'Для аптек', item: 'https://aptekaa.ru/dlya-aptek' },
        ],
      },
      {
        '@type': 'WebPage',
        '@id': 'https://aptekaa.ru/dlya-aptek#webpage',
        url: 'https://aptekaa.ru/dlya-aptek',
        name: 'Для аптек — подключение к АптекаА',
        inLanguage: 'ru',
        isPartOf: { '@type': 'WebSite', name: 'АптекаА', url: 'https://aptekaa.ru' },
      },
    ],
  };
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      <ForPharmacies />
    </>
  );
}
