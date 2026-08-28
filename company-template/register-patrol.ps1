# register-patrol.ps1 —— 注册「公司心跳」每日巡检计划任务（保活第③层）
# 用途：让公司拥有独立于用户注意力的心跳——每天自动跑 opc_patrol.py，异常写入
#       workbench/patrol-log.md 并打印待办；总管每会话巡检共享同一份 patrol 清单。
# 用法（公司根，管理员或当前用户 PowerShell）：
#   powershell -ExecutionPolicy Bypass -File register-patrol.ps1 [-Company C001] [-Time 09:00]
# 撤销：schtasks /Delete /TN OPC-Patrol /F
param(
    [string]$Company = "C001",
    [string]$Time = "09:00"
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition   # 公司根
$root = Split-Path -Parent $here                                # OPC 根

# Python 探测（PATH 优先，P26 不写死机器路径）
$py = $null
foreach ($c in @("python", "python3")) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source; break }
}
if (-not $py) { Write-Error "未在 PATH 找到 python/python3（需 >= 3.11）"; exit 1 }

# 公司 ID 反查（company.md 的「公司 ID」），零手动输入
$md = Join-Path $here "company.md"
if (-not (Test-Path $md)) { Write-Error "找不到 $md（请在公司根执行本脚本）"; exit 1 }
$cid = (Select-String -Path $md -Pattern '公司\s*ID\s*[:：]\s*(\S+)' |
        Select-Object -First 1).Matches[0].Groups[1].Value
Write-Host "检测到公司 ID：$cid"

$taskName = "OPC-Patrol"
$action = New-ScheduledTaskAction -Execute $py `
    -Argument "$(Join-Path $root 'opc_patrol.py') --company $cid --quiet"
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "已注册每日心跳 '$taskName'（$Time）：opc_patrol.py --company $cid --quiet"
Write-Host "验证：schtasks /Query /TN $taskName   |   立即试跑：$py $(Join-Path $root 'opc_patrol.py') --company $cid"
