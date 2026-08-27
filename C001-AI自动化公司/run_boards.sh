#!/usr/bin/env bash
# OPC boards entry point (keepalive layer 2) — macOS / Linux / Git-Bash
# Windows 用户请用 run_boards.bat（功能等价）。
# Usage:
#   ./run_boards.sh          regenerate once, then start both watchers
#   ./run_boards.sh once     regenerate once only (for scheduled task / SOP)
set -e
cd "$(dirname "$0")"

echo "[1/2] generating ticket kanban data..."
python3 workbench/generate_tasks.py

echo "[2/2] generating dashboard data (company/team/mydesk)..."
python3 generate_dashboard.py

if [ "$1" = "once" ]; then
    echo "done (one-shot mode). Open dashboard.html"
    exit 0
fi

echo ""
echo "starting watchers (Ctrl+C to stop both; run them in separate terminals for independent control)..."
python3 workbench/generate_tasks.py --watch &
python3 generate_dashboard.py --watch &
wait
