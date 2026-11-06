@echo off
chcp 65001 >nul
rem Faz o sistema abrir sozinho (minimizado) toda vez que o Windows iniciar.
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LAUNCHER=%STARTUP%\Estoque Maxx Auto Ar.bat"
> "%LAUNCHER%" (
  echo @echo off
  echo cd /d "%~dp0."
  echo start "Estoque Maxx Auto Ar" /min cmd /c iniciar.bat
)
if exist "%LAUNCHER%" (
  echo Pronto: o estoque vai abrir sozinho quando o Windows iniciar.
  echo Para desfazer, rode remover-inicio-automatico.bat
) else (
  echo Nao foi possivel criar o atalho em "%STARTUP%".
)
pause
