@echo off
setlocal
cd /d "%~dp0"
title Instalador - Daikin Smart AC
echo ================================================
echo     Instalador do Daikin Smart AC para PC
echo ================================================
echo.

rem ---------- Encontrar (ou instalar) o Python ----------
echo Procurando o Python...
set "PY="
call :achar_python
if defined PY goto :tem_python

echo Python nao encontrado. Instalando automaticamente (winget)...
echo Isso pode levar alguns minutos.
winget install -e --id Python.Python.3.13 --scope user --silent --accept-package-agreements --accept-source-agreements
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY call :achar_python
if defined PY goto :tem_python

echo.
echo  Nao consegui instalar o Python sozinho.
echo  Baixe em https://www.python.org/downloads/ , marque
echo  "Add python.exe to PATH" e rode este instalador de novo.
start "" "https://www.python.org/downloads/"
pause
exit /b 1

:tem_python
echo OK: %PY%
echo Abrindo o assistente de configuracao...
for %%d in ("%PY%") do set "PYW=%%~dpdpythonw.exe"
if not exist "%PYW%" set "PYW=%PY%"
start "" "%PYW%" "%~dp0assistente.pyw"
exit /b 0

rem ---------- funcao: acha um Python funcionando ----------
:achar_python
for /f "delims=" %%i in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%i"
if defined PY exit /b 0
for /f "delims=" %%i in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%i"
exit /b 0
