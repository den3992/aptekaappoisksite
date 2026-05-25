import './globals.css';
import Footer from '../components/Footer';

export const metadata = {
  // template НЕ ставим — иначе title из leaf-страниц, у которых уже есть
  // «— АптекаА» в строке, получают второй суффикс. Каждая страница пишет
  // полное название, какое нужно показать в выдаче.
  title: {
    default: 'АптекаА — аптечная справочная Москвы и СПб: поиск лекарств, цены и наличие',
  },
  description: 'Бесплатная аптечная справочная по Москве и СПб: поиск лекарств, цены и наличие в 2000+ аптеках. Адреса, режим работы, аналоги препаратов. Без регистрации.',
  metadataBase: new URL('https://aptekaa.ru'),
  openGraph: {
    type: 'website',
    siteName: 'АптекаА',
    locale: 'ru_RU',
    images: [{ url: 'https://aptekaa.ru/og-image.png?v=2', width: 512, height: 512 }],
  },
  twitter: { card: 'summary' },
};

export default function RootLayout({ children }) {
  return (
    <html lang="ru">
      <body className="min-h-[100dvh] flex flex-col overflow-x-clip bg-white">
        <main className="flex-1">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
