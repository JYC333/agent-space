# agent-space TS Control Plane — multi-stage build
#
# Build context: the REPO ROOT (not control-plane), because the control
# plane has a file: dependency on ../packages/protocol that must be present at
# install time. Compose sets `context: ../../` and
# `dockerfile: control-plane/Dockerfile`.
#
# This image serves TS-owned control-plane routes and proxies unowned /api/v1/*
# paths to the Python backend via the temporary fallback proxy. The production
# image runs compiled JS (not tsx/ts-node).

# ---- deps: install node_modules and build the local protocol package ----------
FROM node:20-slim AS deps
WORKDIR /app

ENV NPM_CONFIG_FETCH_RETRIES=5 \
    NPM_CONFIG_FETCH_RETRY_MINTIMEOUT=20000 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000

# Build toolchain for native modules (node-pty hosts the CLI login PTY).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

COPY packages/protocol/package.json ./packages/protocol/package.json
COPY packages/protocol/tsconfig.json packages/protocol/tsconfig.build.json ./packages/protocol/
COPY packages/protocol/src ./packages/protocol/src

COPY control-plane/package.json control-plane/package-lock.json ./control-plane/
WORKDIR /app/control-plane
RUN npm ci
RUN ln -s /app/control-plane/node_modules ../packages/protocol/node_modules \
    && ./node_modules/.bin/tsc -p ../packages/protocol/tsconfig.build.json

# ---- build: compile TS -> dist ------------------------------------------------
FROM deps AS build
COPY control-plane/tsconfig.json ./
COPY control-plane/src ./src
RUN npm run build

# ---- dev-runtime: full deps + writable dist for compose hot reload ------------
FROM deps AS dev-runtime
ENV NODE_ENV=development

COPY catalog /app/catalog
COPY control-plane/tsconfig.json ./
COPY control-plane/src ./src
COPY --from=build /app/control-plane/dist ./dist

# CLI login helper processes need a writable HOME before their state is synced
# into the managed profile dir under AGENT_SPACE_HOME. Dev/test compose also
# runs TypeScript watch builds, so the compiled dist trees must be writable by
# the non-root runtime user.
RUN mkdir -p /home/node/.claude \
    && chown -R node:node /home/node /app/control-plane/dist /app/packages/protocol/dist
USER node
ENV HOME=/home/node

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD node -e "fetch('http://localhost:8010/health').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["node", "dist/index.js"]

# ---- prod-deps: production node_modules (with native builds) -------------------
FROM node:20-slim AS prod-deps
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

COPY packages/protocol/package.json ./packages/protocol/package.json
COPY control-plane/package.json control-plane/package-lock.json ./control-plane/
WORKDIR /app/control-plane
RUN npm ci --omit=dev

# ---- runtime: prod deps + compiled output -------------------------------------
FROM node:20-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY packages/protocol/package.json ./packages/protocol/package.json
COPY --from=deps /app/packages/protocol/dist ./packages/protocol/dist
# Built-in catalog definitions served read-only by the catalog module
# (default CONTROL_PLANE_CATALOG_ROOT resolves to /app/catalog).
COPY catalog ./catalog
COPY control-plane/package.json control-plane/package-lock.json ./control-plane/
COPY --from=prod-deps /app/control-plane/node_modules ./control-plane/node_modules
WORKDIR /app/control-plane
RUN ln -s /app/control-plane/node_modules ../packages/protocol/node_modules

COPY --from=build /app/control-plane/dist ./dist

# CLI login helper processes need a writable HOME before their state is synced
# into the managed profile dir under AGENT_SPACE_HOME.
RUN mkdir -p /home/node/.claude && chown -R node:node /home/node
USER node
ENV HOME=/home/node

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD node -e "fetch('http://localhost:8010/health').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["node", "dist/index.js"]
