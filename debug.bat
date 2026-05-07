@echo off
REM Debug script para capturar erros do BirdNET Uploader
REM Execute este arquivo para ver mensagens de erro

setlocal enabledelayedexpansion

cd /d "%~dp0"

echo.
echo ===============================================
echo BirdNET Uploader - DEBUG MODE
echo ===============================================
echo.
echo Tentando executar a aplicacao...
echo.

REM Tentar executar com Python diretamente (mais confiavel)
python -c "import sys; sys.path.insert(0, '.'); from app import *" 2>&1
set exitcode=!errorlevel!

if !exitcode! equ 0 (
    echo.
    echo SUCESSO: Aplicacao iniciada
    echo.
) else (
    echo.
    echo ===============================================
    echo ERRO: Falha ao iniciar (codigo: !exitcode!)
    echo ===============================================
    echo.
    echo Tentando com traceback completo...
    echo.
    python app.py
)

pause
