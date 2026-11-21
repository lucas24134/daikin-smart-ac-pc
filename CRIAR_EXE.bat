@echo off
setlocal
cd /d "%~dp0"
title Criar DaikinSmartAC.exe
echo ================================================
echo   Criando o aplicativo DaikinSmartAC.exe
echo   (so precisa fazer isso uma vez)
echo ================================================
echo.

set "PY="
for /f "delims=" %%i in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%i"
if not defined PY for /f "delims=" %%i in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%i"
if not defined PY (
  echo Python nao encontrado. Rode o INSTALAR.bat primeiro.
  pause
  exit /b 1
)

echo [1/3] Instalando ferramentas (PyInstaller)...
"%PY%" -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller
if errorlevel 1 goto :erro

echo [2/3] Gerando icone...
"%PY%" gerar_icone.py
if errorlevel 1 goto :erro

echo [3/3] Montando o .exe (pode levar alguns minutos)...
"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name DaikinSmartAC --icon daikin.ico ^
  --hidden-import pystray._win32 ^
  --collect-submodules pyiotdevice ^
  --collect-submodules zeroconf ^
  --collect-submodules Crypto ^
  app.py
if errorlevel 1 goto :erro

copy /y "dist\DaikinSmartAC.exe" "DaikinSmartAC.exe" >nul
rmdir /s /q build 2>nul
del /q DaikinSmartAC.spec 2>nul

echo.
echo ================================================
echo  Pronto! Criado: %~dp0DaikinSmartAC.exe
echo.
echo  - De dois cliques nele para abrir o painel.
echo  - Pode mandar SO esse arquivo para outra pessoa:
echo    ela nao precisa instalar Python.
echo ================================================
explorer /select,"%~dp0DaikinSmartAC.exe"
pause
exit /b 0

:erro
echo.
echo Algo deu errado. Tire um print desta janela e mande.
pause
exit /b 1
