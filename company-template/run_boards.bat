@echo off
rem OPC boards entry point -- Windows
rem 决策 #18：日常数据刷新由 OPC 服务（opc_service.py）常驻负责；
rem 本脚本降级为手动应急的一次性生成工具（"once" 模式）或临时监听（默认）
rem Mechanism code lives at OPC root (opc_tickets.py / opc_dashboards.py).
rem This is a thin company-side wrapper: resolve company id, call root modules.
rem Usage:
rem   run_boards.bat         regenerate once, then start both watchers
rem   run_boards.bat once    regenerate once only (for scheduled task / SOP)
setlocal
cd /d "%~dp0"

rem Walk up from company root to OPC root (dir containing opc.toml)
set "ROOT=%~dp0"
:findroot
if exist "%ROOT%opc.toml" goto :gotroot
for %%I in ("%ROOT%..") do set "ROOT=%%~fI"
if "%ROOT%"=="%ROOT:~0,3%" goto :noroot
set "ROOT=%ROOT%\"
goto :findroot
:noroot
echo ERROR: opc.toml not found ^(not inside an OPC repo?^)
exit /b 1
:gotroot

echo [1/2] generating ticket kanban data...
python "%ROOT%opc_tickets.py" --dir "%CD%"
if errorlevel 1 goto :err

echo [2/2] generating dashboard data ^(company/team/mydesk^)...
python "%ROOT%opc_dashboards.py" --dir "%CD%"
if errorlevel 1 goto :err

if /i "%~1"=="once" (
    echo done ^(one-shot mode^). Open dashboard.html
    exit /b 0
)

echo.
echo starting watchers ^(close windows to stop^)...
start "kanban-watcher" cmd /c "python "%ROOT%opc_tickets.py" --dir "%CD%" --watch"
start "dashboard-watcher" cmd /c "python "%ROOT%opc_dashboards.py" --dir "%CD%" --watch"
echo watchers started. Open dashboard.html
exit /b 0

:err
echo generation FAILED, see errors above.
exit /b 1
