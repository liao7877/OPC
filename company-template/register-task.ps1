# 注册 Windows 计划任务：开机自启看板双 watcher（保活第②层）
# 用法（管理员或当前用户 PowerShell）：powershell -ExecutionPolicy Bypass -File register-task.ps1
# 撤销：schtasks /Delete /TN OPC-BoardsWatch-<公司ID> /F

# 公司 ID 反查（company.md），任务名按公司隔离（多公司互不覆盖）
$md = Join-Path $PSScriptRoot "company.md"
$cid = ""
if (Test-Path $md) { $cid = (Select-String -Path $md -Pattern '公司\s*ID\s*[:：]\s*(\S+)' |
        Select-Object -First 1).Matches[0].Groups[1].Value }
if (-not $cid) { $cid = "default" }
$taskName = "OPC-BoardsWatch-$cid"
$bat = Join-Path $PSScriptRoot "run_boards.bat"

$action  = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "已注册计划任务 '$taskName'：登录时自动运行 run_boards.bat（拉起双 watcher）。"
Write-Host "验证：schtasks /Query /TN $taskName"
