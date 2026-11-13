@echo off
chcp 65001 >nul
cd /d "%~dp0"
title JARVIS OS - atualizar
REM Arraste o zip da versão nova em cima deste arquivo. Sem zip: git pull (clone) ou baixa do GitHub.
REM ATUALIZAR.bat --voltar  volta para a versão anterior.
if not exist "backend\.venv\Scripts\python.exe" (
  echo O JARVIS ainda nao foi instalado nesta pasta: rode o INICIAR.bat primeiro.
  pause
  exit /b 1
)
"backend\.venv\Scripts\python.exe" "backend\scripts\atualizar.py" %*
echo.
pause
