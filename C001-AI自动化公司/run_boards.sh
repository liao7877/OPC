#!/usr/bin/env bash
# OPC boards entry point — macOS / Linux / Git-Bash
# 机制代码已上提 OPC 根（opc_tickets.py / opc_dashboards.py），本脚本只是公司级薄壳：
# 自动反查本公司 ID -> 调根模块生成。python3/python 自动探测（Windows Git Bash 无 python3 也能跑）。
# Usage:
#   ./run_boards.sh          regenerate once, then start both watchers
#   ./run_boards.sh once     regenerate once only (for scheduled task / SOP)
set -e
cd "$(dirname "$0")"

# python3/python 双探测：macOS/Linux 通常只有 python3；Windows Git Bash 常只有 python
PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
    echo "ERROR: python not found in PATH (need >= 3.11)" >&2
    exit 1
fi

# 从公司根向上定位 OPC 根（含 opc.toml 的目录）
ROOT="$PWD"
while [ ! -f "$ROOT/opc.toml" ]; do
    PARENT="$(dirname "$ROOT")"
    if [ "$PARENT" = "$ROOT" ]; then
        echo "ERROR: opc.toml not found (not inside an OPC repo?)" >&2
        exit 1
    fi
    ROOT="$PARENT"
done

echo "[1/2] generating ticket kanban data..."
"$PY" "$ROOT/opc_tickets.py" --dir "$PWD"

echo "[2/2] generating dashboard data (company/team/mydesk)..."
"$PY" "$ROOT/opc_dashboards.py" --dir "$PWD"

if [ "$1" = "once" ]; then
    echo "done (one-shot mode). Open dashboard.html"
    exit 0
fi

echo ""
echo "starting watchers (Ctrl+C to stop both; run them in separate terminals for independent control)..."
"$PY" "$ROOT/opc_tickets.py" --dir "$PWD" --watch &
"$PY" "$ROOT/opc_dashboards.py" --dir "$PWD" --watch &
wait
