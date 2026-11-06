@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Pasta do backup diario. Sem esta linha: OneDrive (se estiver ligado) ou data\backups.
rem Para usar o Google Drive, tire o "rem" da linha abaixo e ajuste o caminho:
rem set "MAXX_BACKUP_DIR=G:\Meu Drive\Backup Estoque Maxx"

if not exist .venv (
  echo Primeira vez: instalando... aguarde.
  python -m venv .venv || (echo Instale o Python em python.org e marque "Add to PATH" & pause & exit /b 1)
  .venv\Scripts\pip install -q -r requirements.txt
)
.venv\Scripts\python run.py
pause
