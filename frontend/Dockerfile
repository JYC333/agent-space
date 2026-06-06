# agent-space Web UI — multi-stage build
#
# Build context: frontend/
# Run via docker-compose in deployments/local/ — the compose file selects a stage
# with `build.target`:
#   - dev / test  → target: dev   (Vite dev server, hot reload, source mounted)
#   - prod        → target: prod  (static `dist` built by Vite, served by nginx)
#
# The default (last) stage is `prod`, so any build that forgets `target:` gets the
# production image rather than a dev server.

# ---- shared dependency layer ----------------------------------------------
FROM node:20-slim AS base

WORKDIR /app

# npm retry config — guards against transient ECONNRESET in WSL2/Docker builds
ENV NPM_CONFIG_FETCH_RETRIES=5 \
    NPM_CONFIG_FETCH_RETRY_MINTIMEOUT=20000 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000

COPY package.json package-lock.json ./
RUN npm ci

# ---- dev: Vite dev server -------------------------------------------------
# Source is bind-mounted by docker-compose, so we don't COPY it here. The PWA
# service worker is intentionally disabled in this stage (vite-plugin-pwa dev
# default), matching how the dev/test environments run.
FROM base AS dev

EXPOSE 5173

# VITE_API_URL/API_URL is injected by docker-compose (http://backend:8000)
CMD ["node_modules/.bin/vite"]

# ---- build: produce the static production bundle --------------------------
FROM base AS build

COPY . .
RUN npm run build

# ---- prod: serve the built bundle via nginx -------------------------------
# This is what makes the PWA installable: real `dist/` output (manifest +
# service worker + precached assets) served over a static web server.
FROM nginx:1.27-alpine AS prod

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
