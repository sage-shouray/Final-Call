# syntax=docker/dockerfile:1.7
FROM node:20-alpine AS base
WORKDIR /app
ENV PNPM_HOME="/pnpm" PATH="$PNPM_HOME:$PATH"
RUN corepack enable

# ---- deps ----
FROM base AS deps
COPY package.json pnpm-lock.yaml* ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store pnpm install --frozen-lockfile

# ---- build ----
FROM deps AS build
COPY . .
RUN pnpm build

# ---- runtime: nginx serves the static bundle ----
FROM nginx:1.25-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.runtime.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
