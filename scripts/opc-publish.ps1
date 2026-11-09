# OPC 发布脚本（PowerShell）：把 main 按 .opc-private-paths.txt 剥离后推送干净分支到公开远程。
# 用法：在仓库根目录执行  .\scripts\opc-publish.ps1
$ErrorActionPreference = 'Stop'

$REPO_ROOT = (git rev-parse --show-toplevel)
Set-Location $REPO_ROOT

$MANIFEST = Join-Path $REPO_ROOT '.opc-private-paths.txt'
$PUBLIC_REMOTE = if ($env:OPC_PUBLIC_REMOTE) { $env:OPC_PUBLIC_REMOTE } else { (git config --get opc.publicRemote) }
if (-not $PUBLIC_REMOTE) { $PUBLIC_REMOTE = 'public' }
$BUILD_DIR = Join-Path $REPO_ROOT '.opc-publish-build'
$PY = if ($env:OPC_PYTHON) { $env:OPC_PYTHON } else {
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if (-not $cmd) { $cmd = Get-Command python3 -ErrorAction SilentlyContinue }
  if (-not $cmd) { throw '找不到 Python，请安装 Python 3.11+ 或设置 OPC_PYTHON' }
  $cmd.Source
}

if (-not (Test-Path $MANIFEST)) { Write-Error "找不到私有清单 $MANIFEST"; exit 1 }

$hasFilter = $true
try { & $PY -m git_filter_repo --version >$null 2>&1 } catch { $hasFilter = $false }
if (-not $hasFilter) { Write-Error '未安装 git-filter-repo：pip install git-filter-repo（或设 OPC_PYTHON 指向已装的 python）'; exit 1 }

$hasRemote = $true
try { $PUBLIC_URL = & git -C $REPO_ROOT remote get-url $PUBLIC_REMOTE 2>$null } catch { $hasRemote = $false }
if (-not $hasRemote) { Write-Error "公开远程 '$PUBLIC_REMOTE' 不存在。请先 git remote add $PUBLIC_REMOTE <公开仓库URL>"; exit 1 }

if (Test-Path $BUILD_DIR) { Remove-Item $BUILD_DIR -Recurse -Force }
git clone $REPO_ROOT $BUILD_DIR | Out-Null
Set-Location $BUILD_DIR

$argsList = @()
foreach ($line in (Get-Content $MANIFEST)) {
  $t = $line.Trim()
  if ($t -eq '' -or $t.StartsWith('#')) { continue }
  $argsList += '--path-glob'; $argsList += $t
}

Write-Host "▶ 按 $($argsList.Count / 2) 条私有规则剥离…"
& $PY -m git_filter_repo --force --invert-paths @argsList
if ($LASTEXITCODE -ne 0) { Write-Error 'filter-repo 失败'; exit 1 }

# ⚠ git-filter-repo 默认会删除 clone 时的 origin 远程（防误推回原仓库）。
# 因此公开远程必须在剥离【之后】重建，否则 push 会报 'origin' does not appear to be a git repository。
git remote remove $PUBLIC_REMOTE 2>$null
git remote add $PUBLIC_REMOTE $PUBLIC_URL

$TARGET_BRANCH = if ($env:OPC_PUBLISH_BRANCH) { $env:OPC_PUBLISH_BRANCH } else { 'main' }
Write-Host "▶ 推送剥离后的分支 '$TARGET_BRANCH' 到公开远程 '$PUBLIC_REMOTE'（force）…"
git push --force $PUBLIC_REMOTE "HEAD:$TARGET_BRANCH"
if ($LASTEXITCODE -ne 0) { Write-Error '推送失败'; exit 1 }

Set-Location $REPO_ROOT
Remove-Item $BUILD_DIR -Recurse -Force
Write-Host "✔ 发布完成。forkers 可从 $PUBLIC_REMOTE 拉取；如历史已变，需 rebase。"
