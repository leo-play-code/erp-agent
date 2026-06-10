# 前端（Next.js 16）容器。rewrites 把 /api、/files 同源代理到後端；
# BACKEND_ORIGIN 在 build 與 runtime 都指向叢集內的 erp-api Service。
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG BACKEND_ORIGIN=http://erp-api:8000
ENV BACKEND_ORIGIN=$BACKEND_ORIGIN
RUN npm run build

FROM node:20-slim
WORKDIR /app
ENV NODE_ENV=production
# runtime 也要：next start 載入 next.config.ts 時 rewrites() 讀這個值
ENV BACKEND_ORIGIN=http://erp-api:8000
COPY --from=build /app/.next ./.next
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/public ./public
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/next.config.ts ./next.config.ts
EXPOSE 3000
CMD ["node_modules/.bin/next", "start", "-p", "3000"]
