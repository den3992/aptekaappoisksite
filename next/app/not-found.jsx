import NotFound from '../components/NotFound';

// Глобальный not-found boundary. Рендерится, когда server-компонент вызывает
// notFound() (например, невалидный город в app/[city]/layout.jsx) — Next.js
// при этом отдаёт корректный HTTP 404, а не soft-404 (200 + контент «404»),
// который Яндекс штрафует.
export const metadata = {
  title: 'Страница не найдена — АптекаА',
  robots: { index: false, follow: false },
};

export default function NotFoundPage() {
  return <NotFound />;
}
