import { redirect } from 'next/navigation';

// Корневой URL `/` — у нас канонический город Москва (как в текущем CRA).
// 308 redirect отдаёт edge nginx через Next.js, поисковики и пользователи
// уходят на /msk без задержки.
export default function Root() {
  redirect('/msk');
}
