@echo off
cd /d "%~dp0fastapi"
call .venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
