@echo off
rem JARVIS OS 0.3 - teste direto da fita de LED ELK-BLEDDM (sem o nucleo).
rem Envia: ligar, azul, desligar e pergunta se a fita mudou. Feche o app do celular antes.
rem Opcoes: --endereco BE:27:53:00:BC:1B  --completo (mais cores)  --inspecionar (lista caracteristicas)
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist backend\.venv\Scripts\python.exe goto semvenv
cd backend
.venv\Scripts\python.exe -c "import bleak" >nul 2>&1 || .venv\Scripts\python.exe -m pip install bleak
.venv\Scripts\python.exe scripts\teste_led.py --perguntar %*
goto fim
:semvenv
echo Rode o INICIAR.bat uma vez antes (ele cria o ambiente do backend).
:fim
pause
