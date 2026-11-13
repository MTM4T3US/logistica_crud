@echo off
rem JARVIS OS - abre o JARVIS como programa (sem janela preta): HUD em janela propria + icone na bandeja.
rem Atalhos: Ctrl+Alt+J abre o HUD; Ctrl+Alt+Espaco fala. Para criar atalhos e iniciar com o Windows: INSTALAR_ATALHOS.bat
setlocal
cd /d "%~dp0"
if not exist backend\.venv\Scripts\pythonw.exe goto preparar
if not exist dist\index.html goto preparar
backend\.venv\Scripts\python.exe -c "import pystray, PIL" >nul 2>&1 || backend\.venv\Scripts\python.exe -m pip install --quiet pystray pillow
start "" "%~dp0backend\.venv\Scripts\pythonw.exe" "%~dp0backend\jarvis_app.pyw"
goto fim
:preparar
echo Primeira vez: rode o INICIAR.bat uma vez (ele instala tudo). Depois use este JARVIS.bat.
pause
:fim
