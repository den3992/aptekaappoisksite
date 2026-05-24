export default function Home() {
  return (
    <main className="p-8 font-sans">
      <h1 className="text-3xl font-bold text-emerald-700">Next.js скелет жив</h1>
      <p className="mt-2 text-slate-600">
        Phase 0 миграции CRA → Next.js. Контейнер собирается,
        Server Components рендерятся. До cutover ещё далеко —
        production отдаёт CRA как обычно.
      </p>
    </main>
  );
}
