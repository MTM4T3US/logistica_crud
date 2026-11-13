@echo off
rem JARVIS OS - cria atalhos "JARVIS" na Area de Trabalho e no Menu Iniciar e pergunta se deve iniciar com o Windows.
setlocal
cd /d "%~dp0"
if not exist backend\.venv\Scripts\pythonw.exe goto preparar
backend\.venv\Scripts\python.exe -c "import pystray, PIL" >nul 2>&1 || backend\.venv\Scripts\python.exe -m pip install --quiet pystray pillow
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w = New-Object -ComObject WScript.Shell; foreach ($d in @([Environment]::GetFolderPath(Desktop), [Environment]::GetFolderPath(Programs))) { $l = $w.CreateShortcut((Join-Path $d JARVIS.lnk)); $l.TargetPath = %~dp0backend\.venv\Scripts\pythonw.exe; $l.Arguments = \"%~dp0backend\jarvis_app.pyw\"; $l.WorkingDirectory = %~dp0backend; $l.IconLocation = %~dp0backend\app\static\jarvis.ico; $l.Description = JARVIS OS; $l.Save() }"
echo Atalhos "JARVIS" criados na Area de Trabalho e no Menu Iniciar.
choice /M "Iniciar o JARVIS junto com o Windows (so na bandeja, sem abrir janela)"
if errorlevel 2 goto nao
backend\.venv\Scripts\python.exe "%~dp0backend\jarvis_app.pyw" --autostart on
goto fim
:nao
backend\.venv\Scripts\python.exe "%~dp0backend\jarvis_app.pyw" --autostart off
goto fim
:preparar
echo Rode o INICIAR.bat uma vez antes (ele instala tudo).
:fim
pause
