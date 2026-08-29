@echo off
rem OPC boards entry point -- Windows
rem 决策 #18：日常数据刷新由 OPC 服务（opc_service.py）常驻负责；
rem 本脚本降级为手动应急的一次性生成工具（默认 once；watch 为显式应急监听，勿与服务并发）
rem Mechanism code lives at OPC root (opc_tickets.py / opc_dashboards.py).
rem This is a thin company-side wrapper: resolve company id, call root modules.
rem Usage:
rem   run_boards.bat          regenerate once only (default; refresh is owned by opc_service)
rem   run_boards.bat watch    emergency manual watchers (do NOT use while opc_service is running)
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

if /i "%~1"=="watch" goto :watch
echo done ^(one-shot mode^). Open dashboard.html
exit /b 0

:watch
echo.
echo starting emergency watchers ^(close windows to stop^)...
start "kanban-watcher" cmd /c "python "%ROOT%opc_tickets.py" --dir "%CD%" --watch"
start "dashboard-watcher" cmd /c "python "%ROOT%opc_dashboards.py" --dir "%CD%" --watch"
echo watchers started. Open dashboard.html
exit /b 0

:err
echo generation FAILED, see errors above.
exit /b 1
