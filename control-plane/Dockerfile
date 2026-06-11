# agent-space TS Control Plane — multi-stage build
#
# Build context: the REPO ROOT (not control-plane), because the control
# plane has a file: dependency on ../packages/protocol that must be present at
# install time. Compose sets `context: ../../` and
# `dockerfile: control-plane/Dockerfile`.
#
# Python remains the sole authority; this image only serves TS-owned control-plane
# routes and proxies everything else under /api/v1/* to the Python backend via the
# temporary legacy proxy. The production image runs compiled JS (not tsx/ts-node).

# ---- deps: install node_modules (incl. the local protocol file dependency) ----
FROM node:20-slim AS deps
WORKDIR /app

ENV NPM_CONFIG_FETCH_RETRIES=5 \
    NPM_CONFIG_FETCH_RETRY_MINTIMEOUT=20000 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000

# The protocol package is source-only (no build step); its package.json + src are
# enough to satisfy the control plane's `file:../packages/protocol` dependency.
COPY packages/protocol/package.json ./packages/protocol/package.json
COPY packages/protocol/src ./packages/protocol/src

COPY control-plane/package.json control-plane/package-lock.json ./control-plane/
WORKDIR /app/control-plane
RUN npm ci

# ---- build: compile TS -> dist ------------------------------------------------
FROM deps AS build
COPY control-plane/tsconfig.json ./
COPY control-plane/src ./src
RUN npm run build

# ---- runtime: prod deps + compiled output -------------------------------------
FROM node:20-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production

COPY packages/protocol/package.json ./packages/protocol/package.json
COPY packages/protocol/src ./packages/protocol/src
# Built-in catalog definitions served read-only by the catalog module
# (default CONTROL_PLANE_CATALOG_ROOT resolves to /app/catalog).
COPY catalog ./catalog
COPY control-plane/package.json control-plane/package-lock.json ./control-plane/
WORKDIR /app/control-plane
RUN npm ci --omit=dev

COPY --from=build /app/control-plane/dist ./dist

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD node -e "fetch('http://localhost:8010/health').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["node", "dist/index.js"]
