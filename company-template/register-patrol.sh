#!/usr/bin/env bash
# register-patrol.sh —— 注册「公司心跳」每日巡检 crontab（自举化薄壳）
# 定时逻辑唯一来源：opc_patrol.py --register-heartbeat（--bootstrap 也会自动挂，无需手动跑本脚本）。
# 用法（公司根）：./register-patrol.sh [公司ID] [HH:MM]   # 默认反查 company.md、09:00
# 撤销：python opc_patrol.py --unregister-heartbeat --company <公司ID>
set -e
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then echo "ERROR: python/python3 未在 PATH（需 >= 3.11）" >&2; exit 1; fi
ARGS="--register-heartbeat --at ${2:-09:00}"
[ -n "${1:-}" ] && ARGS="$ARGS --company $1"
exec "$PY" "$ROOT/opc_patrol.py" $ARGS
