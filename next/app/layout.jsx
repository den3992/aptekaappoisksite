import './globals.css';
import Script from 'next/script';
import Footer from '../components/Footer';

// Я.Метрика counter ID — установлен в CRA-версии сайта, перенесён в Next.js
// при Phase 9 cleanup. Без этого счётчика обрывается:
//   • привязка региона в Я.Бизнес (критично для геозависимого SEO),
//   • поведенческие факторы (Шаги 13-14 SEO-плана),
//   • статистика трафика / источников.
const YM_COUNTER = 109146716;

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
        {/* Я.Метрика — strategy="afterInteractive" грузит счётчик после
            hydration, не блокируя FCP/LCP. */}
        <Script
          id="yandex-metrika"
          strategy="afterInteractive"
          dangerouslySetInnerHTML={{
            __html: `
              (function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};
              m[i].l=1*new Date();
              for (var j = 0; j < document.scripts.length; j++) {if (document.scripts[j].src === r) { return; }}
              k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)})
              (window, document, "script", "https://mc.yandex.ru/metrika/tag.js", "ym");
              ym(${YM_COUNTER}, "init", { defer:true, clickmap:true, trackLinks:true, accurateTrackBounce:true, webvisor:true });
            `,
          }}
        />
        <noscript><div><img src={`https://mc.yandex.ru/watch/${YM_COUNTER}`} style={{position:'absolute', left:'-9999px'}} alt="" /></div></noscript>
      </body>
    </html>
  );
}
