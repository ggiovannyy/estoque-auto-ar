@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Pasta do backup diario. Sem esta linha: OneDrive (se estiver ligado) ou data\backups.
rem Para usar o Google Drive, tire o "rem" da linha abaixo e ajuste o caminho:
rem set "MAXX_BACKUP_DIR=G:\Meu Drive\Backup Estoque Maxx"

if not exist .venv (
  echo Primeira vez: instalando... aguarde.
  py -3 -m venv .venv 2>nul || python -m venv .venv || (echo Instale o Python em python.org e marque "Add to PATH" & pause & exit /b 1)
)
rem Reinstala as dependencias so quando requirements.txt mudar (ex.: depois de uma atualizacao).
fc /b requirements.txt .venv\requirements.installed >nul 2>&1 || (
  echo Instalando dependencias...
  .venv\Scripts\python -m pip install -q -r requirements.txt || (echo Falha ao instalar. Verifique a internet. & pause & exit /b 1)
  copy /y requirements.txt .venv\requirements.installed >nul
)
.venv\Scripts\python run.py
pause
