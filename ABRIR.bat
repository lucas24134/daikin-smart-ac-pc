@echo off
rem Abre o Daikin Smart AC sem deixar janela de console aberta.
cd /d "%~dp0"
set "PYW="
for /f "delims=" %%i in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do set "PYW=%%i"
if not defined PYW (
  echo Python nao encontrado. Rode o INSTALAR.bat primeiro.
  pause
  exit /b 1
)
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" "%~dp0bandeja.pyw"
exit /b 0
