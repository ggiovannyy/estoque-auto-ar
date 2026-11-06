@echo off
chcp 65001 >nul
set "LAUNCHER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Estoque Maxx Auto Ar.bat"
if exist "%LAUNCHER%" (del "%LAUNCHER%" & echo Inicio automatico removido.) else (echo O inicio automatico nao estava instalado.)
pause
