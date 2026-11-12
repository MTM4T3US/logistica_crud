@echo off
rem Inicia o prototipo JARVIS HUD: instala as dependencias na primeira vez e abre o navegador.
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 goto semnode
if exist node_modules goto iniciar
echo Instalando dependencias. Isso acontece so na primeira vez...
call npm install
if errorlevel 1 goto erro
:iniciar
echo Abrindo o JARVIS HUD no navegador. Feche esta janela para encerrar.
call npm run dev -- --open
goto fim
:semnode
echo Node.js nao foi encontrado. Instale a versao LTS em https://nodejs.org e execute este arquivo de novo.
goto fim
:erro
echo A instalacao das dependencias falhou. Veja a mensagem acima.
:fim
pause
