@echo off
rem JARVIS OS 0.5 - configura as luzes Smart Life / Tuya (controle pela rede local).
rem Opcoes: --testar (pisca cada luz)  --refazer (busca as chaves de novo)
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist backend\.venv\Scripts\python.exe goto semvenv
cd backend
.venv\Scripts\python.exe -c "import tinytuya" >/dev/null 2>&1 || .venv\Scripts\python.exe -m pip install tinytuya
.venv\Scripts\python.exe scripts\configurar_luzes.py %*
goto fim
:semvenv
echo Rode o INICIAR.bat uma vez antes (ele cria o ambiente do backend).
:fim
pause
