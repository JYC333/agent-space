# agent-space Web UI — Vite dev server
#
# Build context: frontend/
# Run via docker-compose in deployments/local/
#
# VITE_API_URL is passed at runtime so the dev-server proxy reaches
# the backend container by its Compose service name instead of localhost.

FROM node:20-slim

WORKDIR /app

# npm retry config — guards against transient ECONNRESET in WSL2/Docker builds
ENV NPM_CONFIG_FETCH_RETRIES=5 \
    NPM_CONFIG_FETCH_RETRY_MINTIMEOUT=20000 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

# VITE_API_URL is injected by docker-compose (http://backend:8000)
CMD ["node_modules/.bin/vite"]
