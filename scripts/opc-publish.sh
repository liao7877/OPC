#!/usr/bin/env bash
# Default: offline sanitized build. Explicit --push publishes after verification.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
PY="${OPC_PYTHON:-python3}"
exec "$PY" "$ROOT/opc_publish.py" "$@"
