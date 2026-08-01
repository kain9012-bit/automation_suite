\
@echo off
setlocal

cd /d "%~dp0"

echo [1/3] Removing previous build output...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [2/3] Building onedir package...
py -3.12 -m PyInstaller --noconfirm automation_suite_onedir.spec
if errorlevel 1 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo [3/3] Build completed.
echo Output folder:
echo %cd%\dist\automation_suite
echo.
pause
endlocal
