# Tag records the supported line; the OCI index digest makes rebuilds immutable.
FROM node:24-alpine@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43 AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_BACKEND_BASE_URL=/api
ENV VITE_BACKEND_BASE_URL=${VITE_BACKEND_BASE_URL}
RUN npm run build

FROM nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=2s --start-period=5s --retries=6 \
    CMD wget -qO- http://127.0.0.1:8080/health | grep -q healthy
