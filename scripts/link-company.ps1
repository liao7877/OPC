# link-company.ps1 —— 重新同步 OPC 公司稳定锚（零参数）
# 用途：手动改了公司目录名后，跑一次即可把 companies/<cid> 重指向新位置。
# 发现逻辑在 opc_resolver.py::sync_links（按 company.md 的「公司 ID」扫描发现，零手动输入）。
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition   # scripts/
$root = Split-Path -Parent $here                                # OPC 根
$cands = @(
    "C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
    "python"
    "python3"
)
$py = $null
foreach ($c in $cands) {
    if (Test-Path $c) { $py = $c; break }
}
if (-not $py) { $py = "python" }
& $py (Join-Path $root "opc_resolver.py") --sync-links
