#!/usr/bin/env bash
# sqlite-mcp 一键启动脚本(DM8 的轻量替代,纯 Python 标准库,无任何外部依赖)
# 用法:
#   bash start.sh        前台跑(Ctrl-C 退出)
#   bash start.sh -d     后台跑(日志写到 /tmp/sqlite-mcp.log)

set -euo pipefail
cd "$(dirname "$0")"

# ---- 1. uv 必须存在 -----------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  echo "[ERROR] 没装 uv,先跑: brew install uv  (或 pip install uv)"
  exit 1
fi

# ---- 2. 确保端口没被占(默认 8000,跟着 MCP_PORT 走) ---------------------------
MCP_PORT="${MCP_PORT:-8000}"
export MCP_PORT  # 透传给 uv run python server.py
if lsof -i ":${MCP_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[WARN] 端口 ${MCP_PORT} 已被占用,可能是 dm8-mcp 或 sqlite-mcp 旧进程在跑"
  pgrep -lf "(dm8|sqlite)[-_]mcp.*server\.py" || true
  echo "       如要重启:pkill -f '(dm8|sqlite)[-_]mcp.*server.py'  然后重跑本脚本"
  echo "       或并行跑:  MCP_PORT=8002 bash start.sh -d"
  exit 1
fi

# ---- 3. 装依赖 + 建库(首次) --------------------------------------------------
if [[ ! -d .venv ]]; then
  echo "[INFO] 首次启动,装依赖..."
  uv sync
fi

if [[ ! -f data/enterprise_ops.sqlite ]]; then
  echo "[INFO] 首次启动,初始化样例数据..."
  uv run python init_db.py
fi

# ---- 4. 启动 MCP server -------------------------------------------------------
echo "[INFO] 启动 SQLite MCP server..."
echo "       端点: http://127.0.0.1:${MCP_PORT}/mcp"
echo "       工具: server_info / query_sql / list_tables / describe_table"

if [[ "${1:-}" == "-d" ]]; then
  nohup uv run python server.py > /tmp/sqlite-mcp.log 2>&1 &
  disown
  sleep 2
  echo "[INFO] 后台运行中,PID=$(pgrep -f 'sqlite[-_]mcp.*server\.py')"
  echo "       日志:tail -f /tmp/sqlite-mcp.log"
  echo "       停止:pkill -f 'sqlite[-_]mcp.*server.py'"
else
  exec uv run python server.py
fi
