# Multi-stage build для Next.js standalone.
# Финальный образ — node-alpine + только то, что нужно рантайму (~150 МБ).

FROM node:20-alpine AS deps
WORKDIR /app
COPY next/package.json ./
RUN npm install --no-audit --no-fund

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY next/ ./
# Build args для NEXT_PUBLIC_* — Next.js инлайнит их в client bundle на этапе
# npm run build. Без них process.env.NEXT_PUBLIC_* === undefined в браузере →
# карта аптек / тайлы на странице препарата загружаются без apikey → 429 от
# Yandex после первых же запросов.
ARG NEXT_PUBLIC_YANDEX_MAPS_KEY
ARG NEXT_PUBLIC_YANDEX_TILES_KEY
ENV NEXT_PUBLIC_YANDEX_MAPS_KEY=$NEXT_PUBLIC_YANDEX_MAPS_KEY
ENV NEXT_PUBLIC_YANDEX_TILES_KEY=$NEXT_PUBLIC_YANDEX_TILES_KEY
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
