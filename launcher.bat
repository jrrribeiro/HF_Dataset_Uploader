@echo off
REM BirdNET Uploader Launcher with error capture
REM Keeps the console window open to display errors

setlocal enabledelayedexpansion

echo.
echo ===============================================
echo BirdNET Uploader
echo ===============================================
echo.
echo Launching application...
echo.

REM Change to the script directory
cd /d "%~dp0"

REM Run the executable and capture exit code
birdnet-uploader.exe
set exitcode=!errorlevel!

if not !exitcode! equ 0 (
    echo.
    echo ===============================================
    echo ERROR: Application exited with code !exitcode!
    echo ===============================================
    echo.
    echo The application encountered an error.
    echo Check the error messages above for details.
    echo.
    echo For more information, see:
    echo - WINDOWS_PORTABLE_SETUP.md
    echo - https://github.com/jrrribeiro/BirdNET-Uploader-App/issues
    echo.
    pause
) else (
    echo.
    echo ===============================================
    echo Application closed successfully
    echo ===============================================
    echo.
)

exit /b !exitcode!
