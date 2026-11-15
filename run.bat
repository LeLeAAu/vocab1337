@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Vocab1337

echo ===================================================
echo              DANG KHOI DONG VOCAB1337
echo ===================================================

REM 1. Kiem tra venv cuc bo
if exist ".venv\Scripts\python.exe" (
    set "PY_CMD=.venv\Scripts\python.exe"
    goto CHECK_REQ
)
if exist "venv\Scripts\python.exe" (
    set "PY_CMD=venv\Scripts\python.exe"
    goto CHECK_REQ
)

REM 2. Kiem tra Python 3.11 qua py launcher
py -3.11 -c "import flet" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PY_CMD=py -3.11"
    goto CHECK_REQ
)

REM 3. Kiem tra Python mac dinh
python -c "import flet" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PY_CMD=python"
    goto CHECK_REQ
)

REM 4. Kiem tra duong dan Python 3.11 AppData
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto CHECK_REQ
)

REM 5. Fallback
where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PY_CMD=py"
    goto CHECK_REQ
)

set "PY_CMD=python"

:CHECK_REQ
echo Dang chay bang: %PY_CMD%
echo.

REM Kiem tra va tu dong cai dat thu vien tu requirements.txt neu thieu
if exist "requirements.txt" (
    %PY_CMD% -c "import flet, flet_audio, edge_tts" >nul 2>&1
    if !ERRORLEVEL! neq 0 (
        echo ===================================================
        echo [HE THONG] Phat hien thieu thu vien can thiet!
        echo Dang tu dong cai dat dua tren requirements.txt...
        echo ===================================================
        %PY_CMD% -m pip install -r requirements.txt
        if !ERRORLEVEL! neq 0 (
            echo [CANH BAO] Qua trinh cai dat thu vien gap su co. Dang thu khoi chay...
        ) else (
            echo [THANH CONG] Da cai dat xong cac thu vien can thiet.
        )
        echo.
    )
)

:RUN
%PY_CMD% main.py
if %ERRORLEVEL% neq 0 (
    echo.
    echo ===================================================
    echo [LOI] Ung dung dung voi ma loi %ERRORLEVEL%.
    echo Dang thu tu dong kiem tra va cai dat lai requirements.txt...
    %PY_CMD% -m pip install -r requirements.txt
    echo ===================================================
    pause
)