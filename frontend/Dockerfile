# syntax=docker/dockerfile:1.7
# Stage 1: build the React portal
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# Stage 2: the public edge — static SPA + reverse proxy to Django
FROM nginx:1.27-alpine
RUN apk add --no-cache openssl
COPY --from=build /src/dist /usr/share/nginx/html
COPY nginx/templates/ /etc/nginx/templates/
COPY nginx/40-tls-bootstrap.sh /docker-entrypoint.d/40-tls-bootstrap.sh
COPY nginx/nginx.conf /etc/nginx/nginx.conf
RUN chmod +x /docker-entrypoint.d/40-tls-bootstrap.sh \
 && mkdir -p /var/www/certbot
EXPOSE 80 443
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://127.0.0.1/nginx-health || exit 1
