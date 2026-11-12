@echo off
rem JARVIS OS 0.3 - diagnostico (so le e relata; nao altera nada).
rem Opcoes: --ble (procura fitas de LED por 10 s)  --procurar-leds (acha seus scripts antigos de LED)
setlocal
cd /d "%~dp0"
if not exist backend\.venv\Scripts\python.exe goto semvenv
cd backend
.venv\Scripts\python.exe scripts\diagnostico.py %*
goto fim
:semvenv
echo Rode o INICIAR.bat uma vez antes (ele cria o ambiente do backend).
:fim
pause
