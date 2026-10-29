# 前端镜像：Node 构建静态产物 → nginx 托管并反代 /api。
#
# 本地开发仍走 Vite dev server（./run.sh），本文件只用于容器运行。
# 构建上下文是仓库根目录（见 compose.yaml）：
#   podman build -f docker/frontend.Dockerfile -t self-agent-frontend .

FROM node:22-bookworm-slim AS build

WORKDIR /app

# 依赖层与源码层分开，日常改前端代码不会重新 npm ci。
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
# npm run build = tsc --noEmit && vp build，产物在 /app/dist。
RUN npm run build


FROM nginx:stable-alpine

# 只维护这一份 nginx 配置；本地开发不引用它。
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
