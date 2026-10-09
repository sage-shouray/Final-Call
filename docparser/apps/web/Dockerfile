# syntax=docker/dockerfile:1.7
#
# Builds from the WORKSPACE ROOT, not this folder in isolation — the single
# package-lock.json covering apps/web and packages/shared-types lives there,
# not here. Requires the build context to be the docparser root (see
# docker-compose.yml's "context: .." for this service), not ../apps/web.
#
# Mirrors exactly what CI already runs and proves works: `npm ci` from the
# root, then `npm run build` inside apps/web itself. An earlier version of
# this file assumed pnpm and a pnpm-lock.yaml that has never existed in this
# repository — it built nothing until now.
FROM node:20-alpine AS base
WORKDIR /app

# ---- deps: install the whole workspace from the root lockfile ----
FROM base AS deps
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/shared-types/package.json packages/shared-types/package.json
RUN npm ci

# ---- build: only apps/web's own build script, same as CI ----
FROM deps AS build
COPY . .
WORKDIR /app/apps/web
RUN npm run build

# ---- runtime: nginx serves the static bundle ----
FROM nginx:1.25-alpine AS runtime
COPY --from=build /app/apps/web/dist /usr/share/nginx/html
COPY apps/web/nginx.runtime.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
