#!/usr/bin/env bash
# dm8-mcp 一键启动脚本(纯 Linux native,跟生产部署方式一致)。
#
# Server 用 dmPython 走 TCP 连接串直连 DM8。
#
# 用法:
#   bash start.sh            前台跑(Ctrl-C 退出)
#   bash start.sh -d         后台跑(日志写到 /tmp/dm8-mcp.log)
#
# 环境变量:
#   DM8_CONN_STR     达梦连接串(必填), 例: SYSDBA/<pass>@<dm-host>:5236
#   MCP_PORT         监听端口(默认 8000)
#
# ⚠️ macOS 注意: dmpython 官方只发 Linux wheel(manylinux x86_64 + aarch64),
#                没 macOS 版,所以 `uv sync` 在 Mac 上会失败。Mac 用户请在
#                Linux 主机/容器/WSL 里跑本 server,或走 sqlite_mcp_server
#                那条零外部依赖路径。

set -euo pipefail
cd "$(dirname "$0")"

# ---- 1. uv 必须存在 -----------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  echo "[ERROR] 没装 uv,先跑: pip install uv  (或参考 https://docs.astral.sh/uv/)"
  exit 1
fi

# ---- 2. macOS 提早警告(dmpython 没 macOS wheel) -------------------------------
if [[ "$(uname -s)" == "Darwin" ]]; then
  cat >&2 <<EOF
[ERROR] 检测到 macOS。dmpython 只发 Linux wheel,本 server 在 Mac 上
        装不上。请改走以下任一方式:
          - sqlite_mcp_server (cookbook 路径 B,零外部依赖)
          - SSH 到 Linux 主机/服务器跑本 server
          - WSL / Lima / 任意 Linux 虚拟机跑本 server
EOF
  exit 3
fi

# ---- 3. DM8_CONN_STR 必填 -----------------------------------------------------
if [[ -z "${DM8_CONN_STR:-}" ]]; then
  cat >&2 <<EOF
[ERROR] 请显式设置 DM8_CONN_STR,指向你的达梦实例:

  DM8_CONN_STR="SYSDBA/<password>@<dm-host>:5236" bash start.sh -d

  常见地址写法:
    本机 DM8:        SYSDBA/<pass>@127.0.0.1:5236
    内网 DM8:        SYSDBA/<pass>@10.x.x.x:5236
    同 K8s 集群:     SYSDBA/<pass>@dm8.<ns>.svc.cluster.local:5236

  没有达梦实例?走 sqlite_mcp_server 那条路,零外部依赖。
EOF
  exit 2
fi
export DM8_CONN_STR
SAFE_CONN=$(echo "$DM8_CONN_STR" | sed 's/\/[^@]*@/\/***@/')
echo "[INFO] DM8_CONN_STR = $SAFE_CONN"

# ---- 4. 端口检查(跟着 MCP_PORT 走) --------------------------------------------
MCP_PORT="${MCP_PORT:-8000}"
export MCP_PORT
if lsof -i ":${MCP_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[WARN] 端口 ${MCP_PORT} 已被占,旧 server 还在跑?"
  pgrep -lf "dm8[-_]mcp.*server\.py" || true
  echo "       如要重启: pkill -f 'dm8[-_]mcp.*server.py'  然后重跑本脚本"
  echo "       或并行跑: MCP_PORT=8001 bash start.sh -d"
  exit 1
fi

# ---- 5. 装依赖(首次) ---------------------------------------------------------
if [[ ! -d .venv ]]; then
  echo "[INFO] 首次启动,装依赖 (含 dmpython, ~22 MB)..."
  uv sync
fi

# ---- 6. 启动 ------------------------------------------------------------------
echo "[INFO] 启动 DM8 MCP server..."
echo "       端点: http://127.0.0.1:${MCP_PORT}/mcp"
echo "       工具: server_info / query_sql / list_tables / describe_table"

if [[ "${1:-}" == "-d" ]]; then
  nohup uv run python server.py > /tmp/dm8-mcp.log 2>&1 &
  disown
  sleep 2
  echo "[INFO] 后台运行中,PID=$(pgrep -f 'dm8[-_]mcp.*server\.py')"
  echo "       日志: tail -f /tmp/dm8-mcp.log"
  echo "       停止: pkill -f 'dm8[-_]mcp.*server.py'"
else
  exec uv run python server.py
fi
