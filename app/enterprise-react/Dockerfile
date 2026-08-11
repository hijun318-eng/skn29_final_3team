FROM node:24-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_BACKEND_BASE_URL=http://127.0.0.1:18000
ENV VITE_BACKEND_BASE_URL=${VITE_BACKEND_BASE_URL}
RUN npm run build

FROM nginx:1.28-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=2s --start-period=5s --retries=6 \
    CMD wget -qO- http://127.0.0.1:8080/health | grep -q healthy
