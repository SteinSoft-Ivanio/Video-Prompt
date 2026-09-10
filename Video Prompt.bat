@echo off
setlocal enabledelayedexpansion
title Video -^> Prompt
color 0D

rem UTF-8 no console: sem isso os acentos que o Python imprime saem trocados.
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

rem ---------------------------------------------------------------------------
rem  Onde esta o Python. Reaproveita o ambiente do Whatsapp-Transcritor quando
rem  ele existe: la ja estao o faster-whisper, o PyAV e as DLLs de CUDA, ou seja
rem  3 GB que nao precisam ser instalados duas vezes na mesma maquina.
rem ---------------------------------------------------------------------------
set "PY="
if defined VP_PYTHON if exist "%VP_PYTHON%" set "PY=%VP_PYTHON%"
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%~dp0..\Whatsapp-Transcritor\.venv\Scripts\python.exe" set "PY=%~dp0..\Whatsapp-Transcritor\.venv\Scripts\python.exe"

if not defined PY (
    echo.
    echo  [ERRO] Nao achei um ambiente Python com as dependencias.
    echo.
    echo  Opcao A - reaproveitar o do Whatsapp-Transcritor ^(recomendado^):
    echo     deixe as duas pastas lado a lado em C:\Desenvolvimento\Interno
    echo.
    echo  Opcao B - ambiente proprio, nesta pasta:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

rem Se um video foi arrastado sobre o .bat, usa ele direto.
set "VIDEO=%~1"
if defined VIDEO goto :validar

:perguntar
cls
echo.
echo  ============================================
echo    VIDEO -^> PROMPT
echo  ============================================
echo.
echo  Cole o caminho do video e tecle ENTER.
echo  ^(ou arraste o arquivo em cima deste .bat^)
echo.
set "VIDEO="
set /p "VIDEO=  Video: "
if not defined VIDEO goto :perguntar

:validar
set VIDEO=!VIDEO:"=!
if not exist "!VIDEO!" (
    echo.
    echo  [ERRO] Arquivo nao encontrado: !VIDEO!
    echo.
    pause
    set "VIDEO="
    goto :perguntar
)

echo.
echo  ---- O que e esta gravacao? ----
echo    [1] Bug / problema que o cliente esta mostrando
echo    [2] Sistema antigo do cliente ^(levantamento de telas e regras^)
echo.
set "OP="
set /p "OP=  Modo [1]: "
if "!OP!"=="2" (set "MODO=sistema") else (set "MODO=bug")

echo.
"!PY!" "%~dp0app\videoprompt.py" "!VIDEO!" --modo !MODO!

echo.
pause
endlocal
exit /b
