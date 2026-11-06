@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
  echo Primeira vez: instalando... aguarde.
  python -m venv .venv || (echo Instale o Python em python.org e marque "Add to PATH" & pause & exit /b 1)
  .venv\Scripts\pip install -q -r requirements.txt
)
.venv\Scripts\python run.py
pause
