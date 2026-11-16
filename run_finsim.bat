@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 goto use_py

where python >nul 2>nul
if errorlevel 1 goto no_python

python -c "import matplotlib, PySide6, yfinance" >nul 2>nul
if errorlevel 1 goto missing_dependencies
python main.py
exit /b %errorlevel%

:use_py
py -3 -c "import matplotlib, PySide6, yfinance" >nul 2>nul
if errorlevel 1 goto missing_dependencies
py -3 main.py
exit /b %errorlevel%

:missing_dependencies
echo No se encontraron las dependencias de FinSim en Python.
echo Instala Python 3.10 o posterior y ejecuta:
echo python -m pip install -r requirements-runtime.txt
pause
exit /b 1

:no_python
echo No se encontro Python. Instala Python 3.10 o posterior.
pause
exit /b 1
