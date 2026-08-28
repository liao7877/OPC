# register-patrol.ps1 —— 注册「公司心跳」每日巡检计划任务（自举化薄壳）
# 定时逻辑唯一来源：opc_patrol.py --register-heartbeat（--bootstrap 也会自动挂，无需手动跑本脚本）。
# 用法（公司根）：powershell -ExecutionPolicy Bypass -File register-patrol.ps1 [-Company C001] [-Time 09:00]
# 撤销：powershell -File register-patrol.ps1 不支持撤销，用 python opc_patrol.py --unregister-heartbeat --company <ID>
param(
    [string]$Company = "",
    [string]$Time = "09:00"
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

$args = @("--register-heartbeat", "--at", $Time)
if ($Company) { $args += @("--company", $Company) }
& $py (Join-Path $root "opc_patrol.py") @args
exit $LASTEXITCODE
