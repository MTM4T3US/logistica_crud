@echo off
rem JARVIS OS 0.3 - instala voz local (Piper), transcricao local (faster-whisper),
rem deteccao local de "Jarvis" (openWakeWord) e Bluetooth (bleak), e baixa os modelos.
rem Uso de disco aproximado: 1 GB. Precisa de internet so durante a instalacao.
setlocal
cd /d "%~dp0"
if not exist backend\.venv\Scripts\python.exe goto semvenv
echo [1/2] Instalando bibliotecas locais...
backend\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r backend\requirements-local.txt
if errorlevel 1 goto erro
echo [2/2] Baixando modelos (voz Piper ~63 MB, Whisper small ~480 MB)...
cd backend
.venv\Scripts\python.exe scripts\baixar_modelos.py %*
if errorlevel 1 goto erro
echo.
echo Pronto. Feche e abra o INICIAR.bat para o nucleo carregar os recursos locais.
goto fim
:semvenv
echo Rode o INICIAR.bat uma vez antes (ele cria o ambiente do backend).
goto fim
:erro
echo.
echo Algo falhou. Veja a mensagem acima.
:fim
pause
