@echo off
rem JARVIS OS 0.2 - instala o que faltar, inicia o nucleo local e abre o HUD no navegador.
setlocal
cd /d "%~dp0"
title JARVIS OS 0.2

where node >nul 2>nul
if errorlevel 1 goto semnode
set PY=python
where py >nul 2>nul
if not errorlevel 1 set PY=py -3
%PY% --version >nul 2>nul
if errorlevel 1 goto sempython

if exist node_modules goto build
echo [1/4] Instalando dependencias do HUD. Isso acontece so na primeira vez...
call npm install
if errorlevel 1 goto erro
:build
echo [2/4] Preparando o HUD...
call npm run build
if errorlevel 1 goto erro

if exist backend\.venv\Scripts\python.exe goto deps
echo [3/4] Criando o ambiente Python do nucleo...
%PY% -m venv backend\.venv
if errorlevel 1 goto erro
:deps
backend\.venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check -r backend\requirements.txt
if errorlevel 1 goto erro

if not exist backend\.env copy backend\.env.example backend\.env >nul
if not exist backend\config\permissions.json copy backend\config\permissions.example.json backend\config\permissions.json >nul

echo [4/4] Iniciando o JARVIS Core em http://127.0.0.1:8765
echo.
echo  - Para ativar a IA, coloque sua chave em backend\.env na linha GEMINI_API_KEY e reinicie.
echo  - Apps e pastas autorizados ficam em backend\config\permissions.json.
echo  - Feche esta janela para encerrar.
echo.
start "" /b cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:8765"
cd backend
.venv\Scripts\python.exe -m app.main
goto fim

:semnode
echo Node.js nao foi encontrado. Instale a versao LTS em https://nodejs.org e execute este arquivo de novo.
goto fim
:sempython
echo Python nao foi encontrado. Instale o Python 3.10 ou mais novo em https://www.python.org/downloads/
echo Marque a opcao "Add python.exe to PATH" e execute este arquivo de novo.
goto fim
:erro
echo.
echo Algo falhou na preparacao. Veja a mensagem acima.
:fim
pause
