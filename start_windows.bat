@echo off
cd /d "%~dp0"
if exist .env (
 for /f "usebackq tokens=1,* delims== eol=#" %%A in (".env") do set "%%A=%%B"
)
python -m uvicorn main:app --host 0.0.0.0 --port 8000
pause
