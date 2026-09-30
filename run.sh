#!/usr/bin/env bash
# =============================================================================
#  一键启动开发环境：FastAPI 后端 + Vite/React 前端
#
#  用法：
#    ./run.sh              启动前后端（依赖缺失时自动安装）
#    ./run.sh --install    强制重新安装依赖后再启动
#    ./run.sh --force      启动前清理本项目上次遗留的后端/前端进程
#    ./run.sh --help       查看帮助
#
#  环境变量：
#    BACKEND_PORT   后端端口（默认 8000；需与 frontend/vite.config.ts 的代理一致）
#    FRONTEND_PORT  前端端口（默认 5173）
#    QUIET_BACKEND  设为 1 则不在终端混入后端日志
#
#  退出：Ctrl+C —— 脚本会同时关闭前后端并释放端口
# =============================================================================

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
LOG_DIR="$ROOT_DIR/logs"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
# 实际监听端口：某些环境（如 VS Code Remote-WSL）会把请求的端口重映射，
# 因此启动后以进程自己报告的端口为准。
BACKEND_ACTUAL_PORT=""
FRONTEND_ACTUAL_PORT=""
QUIET_BACKEND="${QUIET_BACKEND:-0}"

INSTALL=0
FORCE=0
BACKEND_PID=""
FRONTEND_PID=""
BACKEND_TAIL_PID=""
FRONTEND_TAIL_PID=""
CLEANED=0

DATA_DIR="$ROOT_DIR/data"

# 数据目录状态：让「知识库还在不在」一眼可见
data_hint() {
  local docs=0 size="尚未创建"
  if [[ -d "$DATA_DIR" ]]; then
    size="$(du -sh "$DATA_DIR" 2>/dev/null | cut -f1 || echo '?')"
    docs="$(find "$DATA_DIR/documents" -maxdepth 1 -type f 2>/dev/null | wc -l || echo 0)"
  fi
  printf 'data/（%s，已上传文件 %s 个）— 删除该目录会清空知识库与任务记录' "$size" "$docs"
}

info()  { printf '\033[1;34m[run]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[run]\033[0m %s\n' "$*"; }
error() { printf '\033[1;31m[run]\033[0m %s\n' "$*" >&2; }

usage() { sed -n '3,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

port_in_use() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | grep -q ":$port " && return 0
  elif command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && return 0
  fi
  return 1
}

# 递归结束进程及其后代：uv run -> uvicorn -> (--reload 的 multiprocessing worker)
# 只杀顶层 PID 会把 uvicorn 子进程孤儿化，导致端口一直被占。
kill_tree() {
  local signal="$1" pid="$2" child
  if [[ -z "$pid" ]]; then return 0; fi
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    kill_tree "$signal" "$child"
  done
  kill "-$signal" "$pid" 2>/dev/null || true
}

# --- 退出清理 ---------------------------------------------------------------
cleanup() {
  local code=$?
  if [[ $CLEANED -eq 1 ]]; then return; fi
  CLEANED=1
  trap - EXIT INT TERM

  printf '\n'
  info "正在停止服务…"
  if [[ -n "$BACKEND_TAIL_PID" ]]; then kill -TERM "$BACKEND_TAIL_PID" 2>/dev/null || true; fi
  if [[ -n "$FRONTEND_TAIL_PID" ]]; then kill -TERM "$FRONTEND_TAIL_PID" 2>/dev/null || true; fi

  kill_tree TERM "$FRONTEND_PID"
  kill_tree TERM "$BACKEND_PID"
  sleep 2
  # 仍未退出的（含被孤立的子孙进程）强杀
  kill_tree KILL "$FRONTEND_PID"
  kill_tree KILL "$BACKEND_PID"
  wait 2>/dev/null || true

  local held=""
  if port_in_use "${BACKEND_ACTUAL_PORT:-$BACKEND_PORT}"; then held="$held ${BACKEND_ACTUAL_PORT:-$BACKEND_PORT}"; fi
  if port_in_use "${FRONTEND_ACTUAL_PORT:-$FRONTEND_PORT}"; then held="$held ${FRONTEND_ACTUAL_PORT:-$FRONTEND_PORT}"; fi
  if [[ -n "$held" ]]; then
    warn "以下端口仍被占用：$held（可用 ss -ltnp 查看是谁）"
  else
    info "已退出，端口 $BACKEND_PORT / $FRONTEND_PORT 均已释放"
  fi
  exit "$code"
}

# --- 参数 -------------------------------------------------------------------
for arg in "$@"; do
  case "$arg" in
    --install) INSTALL=1 ;;
    --force) FORCE=1 ;;
    -h|--help) usage ;;
    *) error "未知参数：$arg（用 --help 查看用法）"; exit 2 ;;
  esac
done

# --- 前置检查 ---------------------------------------------------------------
require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    error "缺少命令：$1"
    case "$1" in
      uv)       error "请安装 uv：https://docs.astral.sh/uv/" ;;
      node|npm) error "请安装 Node.js 22+：https://nodejs.org/" ;;
    esac
    exit 1
  fi
}
require_cmd uv
require_cmd node
require_cmd npm
require_cmd curl

ensure_env() {
  local env_file="$ROOT_DIR/.env"
  if [[ ! -f "$env_file" ]]; then
    if [[ -f "$ROOT_DIR/.env.example" ]]; then
      cp "$ROOT_DIR/.env.example" "$env_file"
      warn "已根据 .env.example 生成 .env —— 请填入真实的 DEEPSEEK_API_KEY"
    else
      warn "未找到 .env / .env.example"
    fi
  fi
  local key=""
  if [[ -f "$env_file" ]]; then
    key="$(grep -E '^DEEPSEEK_API_KEY=' "$env_file" | head -1 | cut -d= -f2- | tr -d '"'"'"' ' || true)"
  fi
  if [[ -z "$key" || "$key" == "your_api_key_here" ]]; then
    warn "DEEPSEEK_API_KEY 未配置：界面会显示「未配置 API Key」，任务无法真正执行"
  fi
}

maybe_install() {
  if [[ $INSTALL -eq 1 || ! -d "$BACKEND_DIR/.venv" ]]; then
    info "安装后端依赖（uv sync）…"
    ( cd "$BACKEND_DIR" && uv sync )
  fi
  if [[ $INSTALL -eq 1 || ! -d "$FRONTEND_DIR/node_modules" ]]; then
    info "安装前端依赖（npm install）…"
    ( cd "$FRONTEND_DIR" && npm install )
  fi
}

port_pids() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp 2>/dev/null | grep ":$port " | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u
  elif command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u
  fi
}

# 本项目自己的 uvicorn / vite 进程（按进程工作目录判断，绝不误杀其它服务）
our_project_pids() {
  local pid cwd
  for pid in $(pgrep -f 'uvicorn app\.main:app|node_modules/\.bin/vite' 2>/dev/null || true); do
    cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    case "$cwd" in
      "$ROOT_DIR"/*) echo "$pid" ;;
    esac
  done
}

free_stale_ports() {
  local pids pid
  pids="$(our_project_pids | sort -u)"
  if [[ -z "$pids" ]]; then
    return 0
  fi
  info "清理上次遗留的本项目进程：$(echo "$pids" | tr '\n' ' ')"
  for pid in $pids; do kill_tree TERM "$pid"; done
  sleep 1
  for pid in $pids; do kill_tree KILL "$pid"; done
  sleep 1
}

check_ports() {
  if [[ $FORCE -eq 1 ]]; then
    free_stale_ports
  fi

  local bad=0 port pid cmd
  for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    if port_in_use "$port"; then
      bad=1
      error "端口 $port 已被占用："
      for pid in $(port_pids "$port"); do
        cmd="$(ps -o cmd= -p "$pid" 2>/dev/null | tr -s ' ' || true)"
        printf '    pid %s  %s\n' "$pid" "$cmd" >&2
      done
    fi
  done

  if [[ $bad -eq 1 ]]; then
    if [[ $FORCE -eq 1 ]]; then
      error "上面是非本项目的进程，请手动结束（或改用其它端口）"
    else
      warn "若是上次运行遗留，可执行：./run.sh --force （只清理本项目进程；默认端口可用环境变量覆盖）"
    fi
  fi
  return "$bad"
}

dump_log_tail() { tail -n 25 "$1" >&2 2>/dev/null || true; }

# 探测某个端口是否「请求值 == 实际绑定值」。
# 某些环境（VS Code Remote-WSL / 端口转发）会悄悄把绑定重映射到随机端口，
# 用与 Vite 相同的调用方式（host=localhost）验证，避免拿到不稳定的 URL。
probe_port() {
  node -e '
const net = require("net")
const port = Number(process.argv[1])
const server = net.createServer()
server.on("error", () => process.exit(1))
server.listen({ port, host: "localhost" }, () => {
  const actual = server.address()
  server.close(() => process.exit(actual && actual.port === port ? 0 : 1))
})
' "$1" 2>/dev/null
}

# 从期望端口开始逐个探测，返回一个可稳定使用的端口
pick_port() {
  local port="$1" tries="${2:-40}" i=0
  while (( i < tries )); do
    if probe_port "$port"; then echo "$port"; return 0; fi
    i=$((i + 1)); port=$((port + 1))
  done
  echo "$1"
}

# 从进程日志里解析它实际监听的端口（不假定配置值）
parse_port_from_log() {
  # 注意：无匹配时必须返回 0，否则 set -e 会让脚本直接退出
  local file="$1" pattern="$2"
  { grep -a -oE "$pattern" "$file" 2>/dev/null || true; } \
    | { grep -oE '[0-9]+$' || true; } \
    | head -1 || true
}

# --- 启动 -------------------------------------------------------------------
start_backend() {
  info "启动后端（:$BACKEND_PORT）…"
  ( cd "$BACKEND_DIR" && exec uv run uvicorn app.main:app --reload --port "$BACKEND_PORT" ) \
    >"$BACKEND_LOG" 2>&1 &
  BACKEND_PID=$!

  BACKEND_ACTUAL_PORT="$BACKEND_PORT"
  local waited=0 actual=""
  while (( waited < 120 )); do
    actual="$(parse_port_from_log "$BACKEND_LOG" 'https?://[0-9.]+:[0-9]+')"
    if [[ -n "$actual" ]]; then
      BACKEND_ACTUAL_PORT="$actual"
      if [[ "$actual" != "$BACKEND_PORT" ]]; then
        warn "后端实际监听端口是 $actual（请求的 $BACKEND_PORT 被环境重映射）"
      fi
      break
    fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      error "后端启动失败，日志末尾："; dump_log_tail "$BACKEND_LOG"; return 1
    fi
    sleep 0.5; waited=$((waited + 1))
  done

  waited=0
  while (( waited < 60 )); do
    if curl -fsS "http://127.0.0.1:$BACKEND_ACTUAL_PORT/api/health" >/dev/null 2>&1; then return 0; fi
    sleep 0.5; waited=$((waited + 1))
  done
  error "等待后端就绪超时，日志末尾："; dump_log_tail "$BACKEND_LOG"; return 1
}

start_frontend() {
  info "启动前端（:$FRONTEND_PORT）…"
  ( cd "$FRONTEND_DIR" && exec npm run dev -- --port "$FRONTEND_PORT" --strictPort ) \
    >"$FRONTEND_LOG" 2>&1 &
  FRONTEND_PID=$!

  FRONTEND_ACTUAL_PORT="$FRONTEND_PORT"
  local waited=0 actual=""
  while (( waited < 90 )); do
    actual="$(parse_port_from_log "$FRONTEND_LOG" 'https?://(localhost|127\.0\.0\.1|\[::1\]):[0-9]+')"
    if [[ -n "$actual" ]]; then
      FRONTEND_ACTUAL_PORT="$actual"
      if [[ "$actual" != "$FRONTEND_PORT" ]]; then
        warn "前端实际监听端口是 $actual（请求的 $FRONTEND_PORT 被环境重映射，例如 VS Code Remote-WSL）"
      fi
      break
    fi
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
      error "前端启动失败，日志末尾："; dump_log_tail "$FRONTEND_LOG"; return 1
    fi
    sleep 0.5; waited=$((waited + 1))
  done

  if [[ -z "$actual" ]]; then
    error "等待前端启动超时（90s），日志末尾："; dump_log_tail "$FRONTEND_LOG"; return 1
  fi

  waited=0
  while (( waited < 60 )); do
    if curl -fsS "http://127.0.0.1:$FRONTEND_ACTUAL_PORT/" >/dev/null 2>&1; then return 0; fi
    sleep 0.5; waited=$((waited + 1))
  done
  error "前端进程已启动但地址无法访问（:$FRONTEND_ACTUAL_PORT），日志末尾："; dump_log_tail "$FRONTEND_LOG"; return 1
}

# --- 主流程 -----------------------------------------------------------------
info "项目根目录：$ROOT_DIR"
ensure_env
maybe_install
# 环境可能重映射端口：先挑一个「请求=实际」的端口，保证 URL 稳定
PICKED_FRONTEND_PORT="$(pick_port "$FRONTEND_PORT")"
if [[ "$PICKED_FRONTEND_PORT" != "$FRONTEND_PORT" ]]; then
  warn "端口 $FRONTEND_PORT 在当前环境不可用/会被重映射，改用 $PICKED_FRONTEND_PORT"
  FRONTEND_PORT="$PICKED_FRONTEND_PORT"
fi

check_ports || exit 1

trap cleanup EXIT INT TERM HUP

mkdir -p "$LOG_DIR"
: >"$BACKEND_LOG"
: >"$FRONTEND_LOG"

start_backend
start_frontend

cat <<EOF

============================================================
  前端   http://localhost:$FRONTEND_ACTUAL_PORT
  后端   http://127.0.0.1:$BACKEND_ACTUAL_PORT   （接口文档 /docs）
  数据   $(data_hint)
  日志   logs/backend.log · logs/frontend.log
  退出   Ctrl+C（会同时关闭前后端并释放端口）
============================================================

EOF

if [[ "$QUIET_BACKEND" != "1" ]]; then
  tail -n +1 -F "$BACKEND_LOG" 2>/dev/null | sed -u 's/^/[backend]  /' &
  BACKEND_TAIL_PID=$!
fi
tail -n +1 -F "$FRONTEND_LOG" 2>/dev/null | sed -u 's/^/[frontend] /' &
FRONTEND_TAIL_PID=$!

info "服务已就绪，日志开始跟随输出（Ctrl+C 退出）"
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done
info "检测到服务退出，开始清理…"
