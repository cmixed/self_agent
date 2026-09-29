#!/usr/bin/env bash
# =============================================================================
#  一键启动开发环境：FastAPI 后端 + Vite/React 前端
#
#  用法：
#    ./run.sh              启动前后端（依赖缺失时自动安装）
#    ./run.sh --install    强制重新安装依赖后再启动
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
QUIET_BACKEND="${QUIET_BACKEND:-0}"

INSTALL=0
BACKEND_PID=""
FRONTEND_PID=""
BACKEND_TAIL_PID=""
FRONTEND_TAIL_PID=""
CLEANED=0

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
  if port_in_use "$BACKEND_PORT"; then held="$held $BACKEND_PORT"; fi
  if port_in_use "$FRONTEND_PORT"; then held="$held $FRONTEND_PORT"; fi
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

check_ports() {
  local bad=0
  if port_in_use "$BACKEND_PORT"; then
    error "端口 $BACKEND_PORT 已被占用（后端）：请先释放，或 BACKEND_PORT=其他端口（需同步改 vite 代理）"
    bad=1
  fi
  if port_in_use "$FRONTEND_PORT"; then
    error "端口 $FRONTEND_PORT 已被占用（前端）：可用 FRONTEND_PORT=其他端口 覆盖"
    bad=1
  fi
  return "$bad"
}

dump_log_tail() { tail -n 25 "$1" >&2 2>/dev/null || true; }

# --- 启动 -------------------------------------------------------------------
start_backend() {
  info "启动后端（:$BACKEND_PORT）…"
  ( cd "$BACKEND_DIR" && exec uv run uvicorn app.main:app --reload --port "$BACKEND_PORT" ) \
    >"$BACKEND_LOG" 2>&1 &
  BACKEND_PID=$!

  local waited=0
  while (( waited < 120 )); do
    if curl -fsS "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then return 0; fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      error "后端启动失败，日志末尾："; dump_log_tail "$BACKEND_LOG"; return 1
    fi
    sleep 0.5; waited=$((waited + 1))
  done
  error "等待后端就绪超时（120s），日志末尾："; dump_log_tail "$BACKEND_LOG"; return 1
}

start_frontend() {
  info "启动前端（:$FRONTEND_PORT）…"
  ( cd "$FRONTEND_DIR" && exec npm run dev -- --port "$FRONTEND_PORT" --strictPort ) \
    >"$FRONTEND_LOG" 2>&1 &
  FRONTEND_PID=$!

  local waited=0
  while (( waited < 90 )); do
    if curl -fsS "http://127.0.0.1:$FRONTEND_PORT/" >/dev/null 2>&1; then return 0; fi
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
      error "前端启动失败，日志末尾："; dump_log_tail "$FRONTEND_LOG"; return 1
    fi
    sleep 0.5; waited=$((waited + 1))
  done
  error "等待前端就绪超时（90s），日志末尾："; dump_log_tail "$FRONTEND_LOG"; return 1
}

# --- 主流程 -----------------------------------------------------------------
info "项目根目录：$ROOT_DIR"
ensure_env
maybe_install
check_ports || exit 1

trap cleanup EXIT INT TERM

mkdir -p "$LOG_DIR"
: >"$BACKEND_LOG"
: >"$FRONTEND_LOG"

start_backend
start_frontend

cat <<EOF

============================================================
  前端   http://localhost:$FRONTEND_PORT
  后端   http://127.0.0.1:$BACKEND_PORT   （接口文档 /docs）
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
