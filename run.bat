@echo off
cd /d "%~dp0\sap-role-checker"

npx concurrently ^
  "cd backend && py -m uvicorn main:app --reload --port 8000" ^
  "cd frontend && npm run dev"

pause