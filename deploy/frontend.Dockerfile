# Frontend Dockerfile — multi-stage: yarn build → nginx static
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/yarn.lock /app/
RUN yarn install --frozen-lockfile --network-timeout 600000
COPY frontend /app
ARG REACT_APP_BACKEND_URL=https://aptekaa.ru
ARG REACT_APP_YANDEX_MAPS_KEY
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL
ENV REACT_APP_YANDEX_MAPS_KEY=$REACT_APP_YANDEX_MAPS_KEY
ENV GENERATE_SOURCEMAP=false
RUN yarn build

FROM nginx:1.27-alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY deploy/nginx/static.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
