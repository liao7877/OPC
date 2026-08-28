#!/usr/bin/env bash
# register-patrol.sh —— 注册「公司心跳」每日巡检 crontab（macOS/Linux，与 register-patrol.ps1 对应）
# 用途：让公司拥有独立于用户注意力的心跳——每天自动跑 opc_patrol.py（异常写
#       workbench/patrol-log.md 并弹系统通知）；总管每会话按同一份清单处置。
# 用法（公司根）：./register-patrol.sh [公司ID] [HH:MM]   # 默认反查 company.md、09:00
# 撤销：crontab -e 删除含 OPC-Patrol-<公司ID> 的行
set -e
cd "$(dirname "$0")"

cid="${1:-}"
at="${2:-09:00}"
h="${at%%:*}"; m="${at##*:}"
case "$h$m" in *[!0-9]*|"") echo "错误：时间格式应为 HH:MM（如 09:00）"; exit 1;; esac

# Python 探测：macOS/Linux 通常只有 python3（需 >= 3.11）
PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then echo "ERROR: python/python3 未在 PATH（需 >= 3.11）" >&2; exit 1; fi

# 公司 ID：参数显式指定优先，否则反查 company.md（与 resolver.extract_company_id 同口径：
# 截内联注释，ID 行带说明文字不破坏发现）
if [ -z "$cid" ]; then
    [ -f company.md ] || { echo "ERROR: 找不到 company.md（请在公司根执行本脚本）" >&2; exit 1; }
    cid=$(grep -m1 -E '公司[[:space:]]*ID' company.md | sed -E 's/.*ID[：:]?[[:space:]]*\**//' \
        | sed -E 's/[（(].*//' | tr -d '*[:space:]')
fi
[ -n "$cid" ] || { echo "ERROR: 未能确定公司 ID（company.md 缺「公司 ID」声明）" >&2; exit 1; }
echo "检测到公司 ID：$cid"

ROOT="$(cd .. && pwd)"
mark="# OPC-Patrol-$cid"
line="$mark
$m $h * * * cd '$ROOT' && $PY opc_patrol.py --company $cid --quiet"
if crontab -l 2>/dev/null | grep -qF "$mark"; then
    echo "已存在心跳任务 $mark，跳过（如需改时间先 crontab -e 删除旧行）"
else
    (crontab -l 2>/dev/null; echo "$line") | crontab -
    echo "已注册每日心跳 '$mark'（$at）：opc_patrol.py --company $cid --quiet"
fi
echo "验证：crontab -l | grep OPC-Patrol   |   立即试跑：$PY '$ROOT/opc_patrol.py' --company $cid"
