#!/usr/bin/env bash
# start.sh — 一键启动清洗项目：后端 127.0.0.1:8321 + 前端 5173
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

BACKEND_URL="http://127.0.0.1:8321/api/health"
BACKEND_PORT=8321
FRONTEND_URL="http://localhost:5173/"
FRONTEND_PORT=5173
# 等待上限（秒）：首次运行要装依赖，给足时间；可用环境变量覆盖（排查 / 自动化用）
BACKEND_TIMEOUT="${START_BACKEND_TIMEOUT:-900}"
FRONTEND_TIMEOUT="${START_FRONTEND_TIMEOUT:-900}"

echo "========================================"
echo "  清洗项目 — 一键启动"
echo "========================================"

# 端口占用实查：只在失败分支调用，报观察到的状态，不猜原因
port_state() {
  local port="$1" holder=""
  holder="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1)"
  if [ -n "$holder" ]; then
    echo "  ℹ️  端口 ${port} 上现有监听进程：PID ${holder}（$(ps -p "$holder" -o comm= 2>/dev/null)）"
  else
    echo "  ℹ️  端口 ${port} 当前无监听"
  fi
}

# 轮询 URL 到返回 200 为止；启动进程已退出、或等满上限才报，且只报事实 + 指向日志
# $1=名称 $2=URL $3=上限秒数 $4=启动进程 PID $5=端口 $6=等待中提示 $7=上限环境变量名
wait_ready() {
  local name="$1" url="$2" limit="$3" pid="$4" port="$5" hint="$6" envvar="$7"
  local waited=0 code=""
  while [ "$waited" -lt "$limit" ]; do
    code="$(curl -s -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
    if [ "$code" = "200" ]; then
      echo "  ✅ ${name}就绪（等待 ${waited}s）"
      return 0
    fi
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
      echo "  ⚠️  ${name}未就绪：启动进程已退出（详见上方日志）"
      port_state "$port"
      return 1
    fi
    if [ "$waited" -gt 0 ] && [ $((waited % 15)) -eq 0 ]; then
      echo "  ⏳ ${hint}（已等待 ${waited}s）"
    fi
    sleep 1
    waited=$((waited + 1))
  done
  echo "  ⚠️  ${name}未就绪：已等待 ${limit}s 仍未返回 200（详见上方日志）"
  echo "  ℹ️  如仍在装依赖，可调大等待上限：${envvar}=1800 bash scripts/start.sh"
  port_state "$port"
  return 1
}

# ── 后端 ──
echo "[1/2] 启动后端 (127.0.0.1:8321)..."
[ -d "$REPO_ROOT/backend/.venv" ] || echo "  首次运行：正在创建虚拟环境并安装 Python 依赖，请稍候…"
(cd "$REPO_ROOT/backend" && \
  python -m venv .venv && \
  source .venv/bin/activate && \
  pip install -q -r requirements.txt && \
  uvicorn app.server.app:app --host 127.0.0.1 --port 8321 --log-level info) &
BACKEND_PID=$!

BACKEND_OK=0
wait_ready "后端" "$BACKEND_URL" "$BACKEND_TIMEOUT" "$BACKEND_PID" "$BACKEND_PORT" \
  "后端启动中" "START_BACKEND_TIMEOUT" || BACKEND_OK=1

# ── 前端 ──
echo "[2/2] 启动前端 (localhost:5173)..."
[ -d "$REPO_ROOT/frontend/node_modules" ] || echo "  首次运行：正在安装前端依赖 (npm install)，请稍候…"
(cd "$REPO_ROOT/frontend" && \
  export PATH="$HOME/.nvm/versions/node/v24.18.0/bin:$PATH" && \
  npm install --silent && \
  npm run dev) &
FRONTEND_PID=$!

FRONTEND_OK=0
wait_ready "前端" "$FRONTEND_URL" "$FRONTEND_TIMEOUT" "$FRONTEND_PID" "$FRONTEND_PORT" \
  "前端启动中" "START_FRONTEND_TIMEOUT" || FRONTEND_OK=1

echo ""
echo "========================================"
if [ "$BACKEND_OK" -eq 0 ]; then
  echo "  🖥️  后端  →  http://127.0.0.1:8321"
else
  echo "  🖥️  后端  →  未就绪（见上方提示）"
fi
if [ "$FRONTEND_OK" -eq 0 ]; then
  echo "  🌐  前端  →  http://localhost:5173"
else
  echo "  🌐  前端  →  未就绪（见上方提示）"
fi
echo "  ⏹️  Ctrl+C 一键停止"
echo "========================================"

# 自动打开浏览器（仅 macOS）
if [ "$FRONTEND_OK" -eq 0 ] && command -v open &>/dev/null; then
  sleep 1 && open "http://localhost:5173/" &
fi

# 等待两个进程退出
wait
