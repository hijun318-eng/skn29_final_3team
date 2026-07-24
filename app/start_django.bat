@echo off
cd /d "%~dp0django"
call .venv\Scripts\activate.bat
python manage.py runserver 0.0.0.0:8000
