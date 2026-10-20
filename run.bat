@echo off
setlocal
cd /d "%~dp0"
if exist "backend\dist\SAP-Lens.exe" (
    start "" "backend\dist\SAP-Lens.exe"
    exit /b 0
)
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "backend\desktop.py"
    exit /b 0
)
echo Build SAP-Lens.exe first, or create .venv and install backend/requirements-desktop.txt.
exit /b 1
