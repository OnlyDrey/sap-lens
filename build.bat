@echo off
setlocal
cd /d "%~dp0"

echo.
echo ==========================================
echo   SAP Role Checker - Production Build
echo ==========================================
echo.

echo [1/4] Installing frontend dependencies...
cd frontend
call npm install
if errorlevel 1 goto error

echo.
echo [2/4] Building frontend...
call npm run build
if errorlevel 1 goto error

echo.
echo [3/4] Installing backend dependencies...
cd ..\backend
py -m pip install -r requirements.txt
if errorlevel 1 goto error

py -m pip install pyinstaller
if errorlevel 1 goto error

echo.
echo [4/4] Building Windows executable...
py -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --name "SAP Role Checker" ^
    --add-data "..\frontend\dist;frontend\dist" ^
    main.py

if errorlevel 1 goto error

echo.
echo ==========================================
echo   BUILD COMPLETE
echo ==========================================
echo.
echo Application:
echo "%CD%\dist\SAP Role Checker.exe"
echo.
pause
exit /b 0


:error

echo.
echo ==========================================
echo   BUILD FAILED
echo ==========================================
echo.
pause
exit /b 1