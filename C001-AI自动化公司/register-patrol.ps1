# register-patrol.ps1 —— 注册「公司心跳」巡检计划任务（自举化薄壳）
# 节奏：默认每 30 分钟（2026-08-29 拍板；配合通知去重只报新发现）。逻辑唯一来源：opc_patrol.py。
# 用法（公司根）：powershell -ExecutionPolicy Bypass -File register-patrol.ps1 [-Company C001] [-Every 30]
# 撤销：python opc_patrol.py --unregister-heartbeat --company <公司ID>
param(
    [string]$Company = "",
    [string]$Every = "30"
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition
$root = Split-Path -Parent $here

$py = $null
foreach ($c in @("python", "python3")) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source; break }
}
if (-not $py) { Write-Error "未在 PATH 找到 python/python3（需 >= 3.11）"; exit 1 }

$args = @("--register-heartbeat", "--every", $Every)
if ($Company) { $args += @("--company", $Company) }
& $py (Join-Path $root "opc_patrol.py") @args
exit $LASTEXITCODE
