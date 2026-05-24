import './globals.css';
import Footer from '../components/Footer';

export const metadata = {
  title: 'АптекаА — миграция Next.js (в процессе)',
  description: 'Internal preview сайта на Next.js во время миграции с CRA.',
  robots: { index: false, follow: false },
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
