import './globals.css';

export const metadata = {
  title: 'АптекаА — миграция Next.js (Phase 0 скелет)',
  description: 'Internal preview сайта на Next.js во время миграции с CRA. Не индексируется.',
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
