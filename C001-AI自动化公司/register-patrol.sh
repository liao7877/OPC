#!/usr/bin/env bash
# register-patrol.sh —— 注册「公司心跳」巡检任务（自举化薄壳）
# 节奏：默认每 30 分钟（2026-08-29 拍板；配合通知去重只报新发现）。逻辑唯一来源：opc_patrol.py。
# 用法（公司根）：./register-patrol.sh [公司ID] [间隔分钟]   # 默认反查 company.md、30 分钟
# 撤销：python opc_patrol.py --unregister-heartbeat --company <公司ID>
set -e
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then echo "ERROR: python/python3 未在 PATH（需 >= 3.11）" >&2; exit 1; fi
ARGS="--register-heartbeat --every ${2:-30}"
[ -n "${1:-}" ] && ARGS="$ARGS --company $1"
exec "$PY" "$ROOT/opc_patrol.py" $ARGS
