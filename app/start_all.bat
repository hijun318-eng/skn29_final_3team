@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title SensePlace

if not exist "%~dp0logs" mkdir "%~dp0logs"

echo ============================================
echo   SensePlace Server Start
echo   Django:8000 / FastAPI:8001 / React:5173
echo ============================================
echo.
echo Logs: app\logs\django.log / fastapi.log / react.log
echo.

echo [1/3] Django...
cd django
start /b cmd /c "call .venv\Scripts\activate.bat && python manage.py runserver 0.0.0.0:8000 --noreload > %~dp0logs\django.log 2>&1"
cd ..

echo [2/3] FastAPI...
cd fastapi
start /b cmd /c "call .venv\Scripts\activate.bat && python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 > %~dp0logs\fastapi.log 2>&1"
cd ..

echo [3/3] React...
cd react
start /b cmd /c "call npm run dev > %~dp0logs\react.log 2>&1"
cd ..

echo.
echo Waiting 5s for servers...
timeout /t 5 /nobreak >nul
echo.

echo Ports:
netstat -ano | findstr "LISTEN" | findstr "8000 8001 5173"
echo.

echo ============================================
echo   Running
echo   Django:   http://localhost:8000
echo   FastAPI:  http://localhost:8001
echo   React:    http://localhost:5173
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
