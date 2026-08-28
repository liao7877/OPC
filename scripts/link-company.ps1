# link-company.ps1 —— 重新同步 OPC 公司稳定锚（零参数）
# 用途：手动改了公司目录名后，跑一次即可把 companies/<cid> 重指向新位置。
# 发现逻辑在 opc_resolver.py::sync_links（按 company.md 的「公司 ID」扫描发现，零手动输入）。
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition   # scripts/
$root = Split-Path -Parent $here                                # OPC 根
# Python 探测：PATH 上的 python / python3（不写死机器专属路径，P26）
$py = $null
foreach ($c in @("python", "python3")) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source; break }
}
if (-not $py) {
    Write-Error "未在 PATH 找到 python/python3（需 >= 3.11）"
    exit 1
}
& $py (Join-Path $root "opc_resolver.py") --sync-links
exit $LASTEXITCODE
