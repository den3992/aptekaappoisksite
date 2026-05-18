# Frontend Dockerfile — multi-stage: yarn build → nginx static
FROM node:20-alpine AS build
WORKDIR /app
# yarn.lock не закоммичен (gitignore ловит .yarn/* и т.п.), поэтому копируем
# только package.json и даём yarn создать свой lock внутри образа.
COPY frontend/package.json /app/
RUN yarn install --network-timeout 600000
COPY frontend /app
ARG REACT_APP_BACKEND_URL=https://aptekaa.ru
ARG REACT_APP_YANDEX_MAPS_KEY
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL
ENV REACT_APP_YANDEX_MAPS_KEY=$REACT_APP_YANDEX_MAPS_KEY
ARG REACT_APP_YANDEX_TILES_KEY
ENV REACT_APP_YANDEX_TILES_KEY=$REACT_APP_YANDEX_TILES_KEY
ENV GENERATE_SOURCEMAP=false
RUN yarn build

FROM nginx:1.27-alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY deploy/nginx/static.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
