// Скрытая админ-страница: модерация отзывов с фото.
// noindex + не линкуется ниоткуда. Реальный барьер — логин/пароль (JWT).
import AdminPanel from '../../components/AdminPanel';

export const metadata = {
  title: 'Админ — АптекаА',
  robots: { index: false, follow: false },
};

export default function Page() {
  return <AdminPanel />;
}
