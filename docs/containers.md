# 容器运行（Podman / Docker）

本地开发仍然使用 `./run.sh`（Vite dev server + uvicorn）。容器运行是**另一条运行路径**：

```text
浏览器
  │  http://localhost:8080
  ▼
frontend 容器（nginx）
  ├── /        → /usr/share/nginx/html（frontend/dist）
  └── /api/    → http://backend:8000（反向代理，SSE 不缓冲）
                    │
                    ▼
              backend 容器（FastAPI + LangGraph + ChromaDB）
                    │
                    ▼
              ./data（bind mount）
```

- 前端镜像在构建时执行 `npm run build`，运行时不带 Vite / Node；
- 后端只在容器网络内暴露 `8000`，宿主机只看到 `8080`；
- 两个容器共用仓库根目录的 `./data`，与本地开发的数据完全一致；
- `backend/.env` 通过 compose 的 `env_file` 注入，不复制进镜像、不提交仓库。

> ⚠️ 不要同时运行 `./run.sh` 和容器：SQLite / ChromaDB 共用同一份 `data/`，
> 并发写入可能损坏数据。切换运行方式前先停掉另一边。

## 前置条件

| 方式                          | 需要安装                                                           |
| ----------------------------- | ------------------------------------------------------------------ |
| Podman（推荐，本机为 Fedora） | `podman` + `podman-compose`（或较新版本的 `podman compose`） |
| Docker                        | Docker Engine + Compose v2（`docker compose`）                   |

```bash
# Fedora
sudo dnf install -y podman podman-compose
# 验证
podman --version
podman-compose --version
```

## 首次准备

```bash
cd /home/cmixed/code/self_agent

# 1) 环境变量（compose 的 env_file 指向这个文件）
cp backend/.env.example backend/.env
# 编辑 backend/.env，至少填入 DEEPSEEK_API_KEY

# 2) 数据目录（已存在可跳过；rootless Podman 下由当前用户持有）
mkdir -p data
```

`data/` 下的内容与本地开发相同：

| 路径                   | 内容                                     |
| ---------------------- | ---------------------------------------- |
| `data/documents/`    | 上传的原始文档                           |
| `data/chroma/`       | 向量库                                   |
| `data/sqlite/`       | 任务记录、长期记忆、LangGraph checkpoint |
| `data/skills/`       | 技能目录                                 |
| `data/settings.json` | 运行时模型服务商选择                     |
| `data/hf-cache/`     | Embedding 模型缓存（容器内 `HF_HOME`） |

## 启动 / 停止

```bash
# Podman
podman-compose up -d --build

# Docker
docker compose up -d --build
```

打开 [http://localhost:8080](http://localhost:8080)。

```bash
# 查看状态 / 日志
podman-compose ps
podman-compose logs -f backend
podman-compose logs -f frontend

# 健康检查（容器内）
podman exec <backend-container> curl -fsS http://127.0.0.1:8000/api/health

# 停止并删除容器（不会删除 ./data）
podman-compose down
```

Docker 把上面的 `podman-compose` 换成 `docker compose` 即可。

### 代码改动后

镜像里的前后端都是**构建时固化**的，改代码后需要重新构建：

```bash
podman-compose up -d --build
```

只改后端时也可以：

```bash
podman-compose build backend && podman-compose up -d backend
```

## GitHub Actions 自动构建（GHCR）

`.github/workflows/images.yml` 会在 push 到 `master`、推送 `v*` tag、PR 和手动触发时
构建两个镜像，并推送到 GitHub Container Registry：

```text
ghcr.io/<owner>/self-agent-backend:<tag>
ghcr.io/<owner>/self-agent-frontend:<tag>
```

| 事件            | 行为                                            |
| --------------- | ----------------------------------------------- |
| push `master` | 构建并推送 `master`、`sha-xxxx`、`latest` |
| push `v1.0.0` | 构建并推送 `1.0.0`、`1.0`、`sha-xxxx`     |
| Pull Request    | 只构建验证，不推送                              |
| 手动触发        | 构建并推送                                      |

- PR 构建不登录、不推送，fork 的 PR 也能跑；
- 缓存按 backend / frontend 分开（`type=gha`），后端依赖层可复用；
- 后端镜像较大，workflow 仅对 backend 释放 runner 磁盘空间；
- 默认只构建 `linux/amd64`。目标机器是 ARM 时需改为 `ubuntu-24.04-arm`
  或在本地重新构建，不建议用 QEMU 模拟构建 torch；
- 镜像不含 `backend/.env` 和 `data/`，仍然由目标机器在运行时提供。

### 目标机器拉取镜像

GHCR 包默认是 private，需要先登录（PAT 需要 `read:packages`）：

```bash
echo "$CR_PAT" | docker login ghcr.io -u <github用户名> --password-stdin
# 或
podman login ghcr.io -u <github用户名>
```

也可以在 GitHub 的 package 设置里把镜像改成 public，之后匿名即可拉取。

### 用 compose.release.yaml 部署

目标机器只需要：

```text
compose.release.yaml
backend/.env
data/
```

```bash
# 第一次 / 版本升级时拉取
IMAGE_PREFIX=ghcr.io/<owner> TAG=v1.0.0 \
  docker compose -f compose.release.yaml pull
IMAGE_PREFIX=ghcr.io/<owner> TAG=v1.0.0 \
  docker compose -f compose.release.yaml up -d

# Podman
IMAGE_PREFIX=ghcr.io/<owner> TAG=v1.0.0 \
  podman-compose -f compose.release.yaml pull
IMAGE_PREFIX=ghcr.io/<owner> TAG=v1.0.0 \
  podman-compose -f compose.release.yaml up -d
```

`IMAGE_PREFIX` / `TAG` 不传时默认使用 `ghcr.io/cmixed` 和 `latest`；演示和长期部署
建议固定到 `v1.0.0` 或 `sha-xxxx`，不要依赖 `latest`。

> 目标机器如果只有镜像、没有源码，不要用 `compose.yaml` —— 它带 `build:`，
> 会尝试本地构建。用 `compose.release.yaml` 只拉镜像。

## 常用配置

### Embedding 模型缓存

首次上传文档或检索时会下载 `BAAI/bge-small-zh-v1.5`（约 100MB）。compose 已把
`HF_HOME` 固定到 `/app/data/hf-cache`，即宿主机的 `data/hf-cache/`，重建容器不会重复下载。

网络受限时在 `backend/.env` 里加一行（会随 `env_file` 进入容器）：

```env
HF_ENDPOINT=https://hf-mirror.com
```

### 访问宿主机上的 Ollama

容器内的 `127.0.0.1` 是容器自己，不是宿主机。把 `backend/.env` 改成：

```env
# Podman
OLLAMA_BASE_URL=http://host.containers.internal:11434/v1
OLLAMA_MODEL=qwen3:4b

# Docker Desktop
# OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
```

Docker Engine（Linux）默认没有 `host.docker.internal`，需要在 compose 的 backend
服务下临时加：

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

改完后让后端重新读取环境变量（`env_file` 内容变化不一定被自动检测）：

```bash
podman-compose up -d --force-recreate backend
```

### 端口

默认宿主机 `8080`。被占用时改 `compose.yaml`：

```yaml
ports:
  - "8081:80"
```

后端 `8000` 不发布到宿主机，只通过 nginx 的 `/api` 访问。

### 上传大小

| 位置                           | 上限                                       |
| ------------------------------ | ------------------------------------------ |
| nginx `client_max_body_size` | 300MB（覆盖知识库 100MB 与完整备份 300MB） |
| 知识库导入                     | 100MB（后端校验）                          |
| 完整备份导入                   | 300MB（后端校验）                          |

如果前面还有一层反向代理（NAS、云厂商 LB），也要同步调大它的请求体上限。

## 排错

| 现象                                           | 排查                                                                                                                                 |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `podman-compose` 提示找不到 `backend/.env` | 先 `cp backend/.env.example backend/.env`                                                                                          |
| 打开 8080 是 502                               | `podman-compose ps` 看 backend 是否 healthy；`logs backend` 看启动错误；若只重建过 backend，重启 frontend 刷新 nginx 的 DNS 解析 |
| 上传/导入返回 413                              | 确认使用的是仓库里的 `docker/nginx.conf`；若外层还有代理，同步调大                                                                 |
| SSE 进度不动、最后一次性出现                   | nginx 必须 `proxy_buffering off`；不要在前面再加会缓冲的代理                                                                       |
| 任务执行中途后端重启后显示已取消               | 事件缓冲在进程内存，重启后会把遗留 `running` 标记为 `cancelled`（设计如此）                                                      |
| `data/` 权限错误（Docker）                   | Docker 下容器以 root 写入，宿主机文件属主会变成 root：`sudo chown -R $(id -u):$(id -g) data`                                       |
| Fedora SELinux 下 `permission denied`        | 给 bind mount 加 SELinux 标签：`./data:/app/data:Z`（Docker / Podman 都支持）                                                      |
| 首次检索很慢                                   | 正在下载 Embedding 模型；看 `logs backend` 的 `embedding_download`，或配置 `HF_ENDPOINT`                                       |
| 构建时下载 torch 超时                          | 已设置 `UV_HTTP_TIMEOUT=600`；网络仍慢可重试，或先在本机 `uv sync` 后利用缓存                                                    |

### 关于 rootless Podman

基础 `compose.yaml` 没有使用 `userns_mode: keep-id`，因为该字段 Docker 不认。
rootless Podman 默认把容器 root 映射到当前宿主用户，因此 `./data` 的读写权限正常。
如果你的环境需要显式保留 UID，可另建一个 `compose.podman.yaml` 覆盖文件，而不是改基础配置。

## 镜像与构建说明

| 文件                             | 作用                                                               |
| -------------------------------- | ------------------------------------------------------------------ |
| `compose.yaml`                 | 本地构建并启动两个服务、端口、`env_file`、数据挂载、健康检查     |
| `compose.release.yaml`         | 目标机器只拉 GHCR 镜像，不含 `build:`                            |
| `.github/workflows/images.yml` | push / tag / PR / 手动触发构建并推送 GHCR                          |
| `docker/backend.Dockerfile`    | `python:3.14-slim-bookworm` + uv + CPU-only torch                |
| `docker/frontend.Dockerfile`   | `node:22-bookworm-slim` 构建 → `nginx:stable-alpine` 运行     |
| `docker/nginx.conf`            | 静态托管、`/api` 反代、SSE、上传上限、gzip、SPA fallback         |
| `.dockerignore`                | 排除 `data/`、`.env`、`.venv`、`node_modules`、`dist` 等 |

- 后端镜像保持 `/app/backend/app` + `/app/data` 布局，使 `config.py` 推导出的
  数据路径仍是 `/app/data`，无需为容器改业务代码；
- torch 走 `pytorch-cpu` 源（见 `backend/pyproject.toml`），GPU 推理由 Ollama / 云端负责；
- 镜像为 OCI 格式，Podman 构建的镜像 Docker 也能运行。
