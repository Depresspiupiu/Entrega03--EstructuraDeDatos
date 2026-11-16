@echo off
setlocal
cd /d "%~dp0"

python -m PyInstaller --noconfirm --clean --distpath "%TEMP%\FinSimPartsBuild" --workpath "%TEMP%\FinSimPartsBuildWork" FinSimPortable.spec
if errorlevel 1 exit /b %errorlevel%

python -m PyInstaller --noconfirm --clean --distpath "%TEMP%\FinSimLauncherBuild" --workpath "%TEMP%\FinSimLauncherBuildWork" FinSimLauncher.spec
if errorlevel 1 exit /b %errorlevel%

python package_finsim_parts.py --app-dir "%TEMP%\FinSimPartsBuild\FinSimPortable" --launcher-exe "%TEMP%\FinSimLauncherBuild\FinSim-Setup.exe" --output-dir "dist\FinSim-Partes"
if errorlevel 1 exit /b %errorlevel%

echo.
echo FinSim esta listo en dist\FinSim-Partes
pause
