@echo off
rem JARVIS OS 0.2.1 - valida a integracao REAL com o Gemini usando a chave de backend\.env
rem Gera um relatorio em backend\samples\validacao.md e amostras de voz em backend\samples\
setlocal
cd /d "%~dp0"
if not exist backend\.venv\Scripts\python.exe goto semvenv
backend\.venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check numpy
cd backend
.venv\Scripts\python.exe scripts\validar_gemini.py %*
echo.
echo Relatorio: backend\samples\validacao.md   Amostras: backend\samples\*.wav
goto fim
:semvenv
echo Rode o INICIAR.bat uma vez antes (ele cria o ambiente do backend).
:fim
pause
