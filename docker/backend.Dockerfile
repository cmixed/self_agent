# 后端镜像：FastAPI + LangGraph + ChromaDB（CPU-only torch）
#
# 布局刻意保持 /app/backend/app 与 /app/data：
# app/core/config.py 通过 __file__ 推导仓库根目录（parents[3]），
# 这样容器内数据路径与本地开发完全一致（/app/data）。
#
# 构建上下文是仓库根目录（见 compose.yaml）：
#   podman build -f docker/backend.Dockerfile -t self-agent-backend .

FROM python:3.14-slim-bookworm

# uv 只用于构建阶段安装依赖；运行时直接用 .venv/bin/uvicorn。
# 使用 latest 标签是为了兼容不同架构；需要完全可复现时可改为固定 tag。
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 模型缓存落到 bind mount（compose 也会显式设置一次）。
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=600 \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv \
    HF_HOME=/app/data/hf-cache

# libgomp1：torch / onnxruntime 的 OpenMP 运行时；curl：healthcheck。
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# 先只复制依赖清单，让「改代码」不触发依赖层重建。
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 再复制源码并安装项目本身（hatchling）。装完清掉 uv 缓存，避免镜像里多出上百 MB。
COPY backend/ ./
RUN uv sync --frozen --no-dev \
    && rm -rf /root/.cache/uv

ENV PATH="/app/backend/.venv/bin:$PATH"

EXPOSE 8000

# 容器内不跑 --reload；任务执行与 SSE 由后端自身管理。
CMD ["/app/backend/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
