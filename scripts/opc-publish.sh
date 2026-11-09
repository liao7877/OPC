#!/usr/bin/env bash
# OPC 发布脚本：把 main（含私有）按 .opc-private-paths.txt 剥离后，推送干净分支到公开远程。
# 用法：./scripts/opc-publish.sh   （在仓库根目录执行）
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

MANIFEST="$REPO_ROOT/.opc-private-paths.txt"
PUBLIC_REMOTE="${OPC_PUBLIC_REMOTE:-$(git config --get opc.publicRemote || echo public)}"
BUILD_DIR="$REPO_ROOT/.opc-publish-build"
PY="${OPC_PYTHON:-python3}"

if [ ! -f "$MANIFEST" ]; then echo "✗ 找不到私有清单 $MANIFEST" >&2; exit 1; fi

# 探测 git-filter-repo 是否可用
if ! "$PY" -m git_filter_repo --version >/dev/null 2>&1; then
  echo "✗ 未安装 git-filter-repo：pip install git-filter-repo（或设 OPC_PYTHON 指向已装的 python）" >&2; exit 1
fi

# 探测公开远程
PUBLIC_URL="$(git -C "$REPO_ROOT" remote get-url "$PUBLIC_REMOTE" 2>/dev/null)" || true
if [ -z "$PUBLIC_URL" ]; then
  echo "✗ 公开远程 '$PUBLIC_REMOTE' 不存在。请先：git remote add $PUBLIC_REMOTE <公开仓库URL>" >&2; exit 1
fi

# 构建发布用临时克隆（不含工作仓库的 pre-push 钩子，故可直推公开远程）
rm -rf "$BUILD_DIR"
git clone "$REPO_ROOT" "$BUILD_DIR" >/dev/null
cd "$BUILD_DIR"

# 清单 → --path-glob 参数（跳过注释/空行）
ARGS=()
while IFS= read -r line; do
  case "$line" in
    ''|\#*) continue ;;
  esac
  ARGS+=( --path-glob "$line" )
done < "$MANIFEST"

echo "▶ 按 $((${#ARGS[@]}/2)) 条私有规则剥离…"
"$PY" -m git_filter_repo --force --invert-paths "${ARGS[@]}"

# ⚠ git-filter-repo 默认会删除 clone 时的 origin 远程（防误推回原仓库）。
# 因此公开远程必须在剥离【之后】重建，否则 push 会报 'origin' does not appear to be a git repository。
git remote remove "$PUBLIC_REMOTE" 2>/dev/null || true
git remote add "$PUBLIC_REMOTE" "$PUBLIC_URL"

TARGET_BRANCH="${OPC_PUBLISH_BRANCH:-main}"
echo "▶ 推送剥离后的分支 '$TARGET_BRANCH' 到公开远程 '$PUBLIC_REMOTE'（force）…"
git push --force "$PUBLIC_REMOTE" "HEAD:$TARGET_BRANCH"

cd "$REPO_ROOT"
rm -rf "$BUILD_DIR"
echo "✔ 发布完成。forkers 可从 $PUBLIC_REMOTE 拉取；如历史已变，需 rebase。"
