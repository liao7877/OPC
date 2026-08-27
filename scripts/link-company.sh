#!/usr/bin/env bash
# link-company.sh —— 重新同步 OPC 公司稳定锚（零参数）
# 用途：手动改了公司目录名后，跑一次即可把 companies/<cid> 重指向新位置。
# 发现逻辑在 opc_resolver.py::sync_links（按 company.md 的「公司 ID」扫描发现，零手动输入）。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # scripts/
ROOT="$(dirname "$SCRIPT_DIR")"                               # OPC 根
PY="$(command -v python3 || command -v python || true)"
"$PY" "$ROOT/opc_resolver.py" --sync-links
