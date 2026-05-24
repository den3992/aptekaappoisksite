/** @type {import('next').NextConfig} */
const nextConfig = {
  // standalone-сборка — минимальный рантайм-образ без node_modules.
  output: 'standalone',
  reactStrictMode: true,
  // Картинки препаратов отдаются с того же origin (frontend nginx) —
  // настроим явно, чтобы next/image мог их оптимизировать когда придёт время.
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: 'aptekaa.ru' },
    ],
  },
};
module.exports = nextConfig;
