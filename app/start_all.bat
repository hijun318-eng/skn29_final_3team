@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title Answervice

if not exist "%~dp0logs" mkdir "%~dp0logs"

echo ============================================
echo   Answervice Server Start
echo   FastAPI:8001 / Enterprise:5173
echo ============================================
echo.
echo Logs: app\logs\fastapi.log / enterprise.log
echo.

echo [1/2] FastAPI...
cd fastapi
start /b cmd /c "call .venv\Scripts\activate.bat && python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 > %~dp0logs\fastapi.log 2>&1"
cd ..

echo [2/2] Enterprise React...
cd enterprise-react
start /b cmd /c "call npm run dev > %~dp0logs\enterprise.log 2>&1"
cd ..

echo.
echo Waiting 5s for servers...
timeout /t 5 /nobreak >nul
echo.

echo Ports:
netstat -ano | findstr "LISTEN" | findstr "8001 5173"
echo.

echo ============================================
echo   Running
echo   FastAPI:    http://localhost:8001
echo   Enterprise: http://localhost:5173
echo ============================================
echo.
echo Close this window to stop all servers.
echo.

pause >nul
echo.
echo Stopping servers...
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM node.exe >nul 2>&1
echo Done.
