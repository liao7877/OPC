@echo off
rem OPC boards entry point (keepalive layer 2). Run from company root.
rem Usage:
rem   run_boards.bat         regenerate once, then start both watchers
rem   run_boards.bat once    regenerate once only (for scheduled task / SOP)
setlocal
cd /d "%~dp0"

echo [1/2] generating ticket kanban data...
python workbench\generate_tasks.py
if errorlevel 1 goto :err

echo [2/2] generating dashboard data (company/team/mydesk)...
python generate_dashboard.py
if errorlevel 1 goto :err

if /i "%~1"=="once" (
    echo done ^(one-shot mode^). Open dashboard.html
    exit /b 0
)

echo.
echo starting watchers (close windows to stop)...
start "kanban-watcher" cmd /c "python workbench\generate_tasks.py --watch"
start "dashboard-watcher" cmd /c "python generate_dashboard.py --watch"
echo watchers started. Open dashboard.html
exit /b 0

:err
echo generation FAILED, see errors above.
exit /b 1
