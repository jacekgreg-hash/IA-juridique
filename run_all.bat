@echo off
setlocal
set "OPENBLAS_NUM_THREADS=1"
set "OMP_NUM_THREADS=1"
set "MKL_NUM_THREADS=1"
set "NUMEXPR_NUM_THREADS=1"
set "RITA_PRELOAD=0"
cd /d %~dp0
rem Python 3.12 pour PaddleOCR. Surcharge possible : set PY312=C:\chemin\python.exe
if not defined PY312 set "PY312=%LOCALAPPDATA%\Python\pythoncore-3.12-64\python.exe"
if not exist "%PY312%" (
  echo [RITA] Python 3.12 introuvable : %PY312%
  echo [RITA] Definissez la variable PY312 avec le chemin de python.exe 3.12
  pause
  exit /b 1
)
start "RITA PaddleOCR" "%ComSpec%" /k ""%PY312%" "%~dp0tools\paddle_ocr_service.py""
timeout /t 2 /nobreak >nul
start "RITA Vision API" "%ComSpec%" /k "cd /d "%~dp0" && python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --log-level info"
echo.
echo [RITA] PaddleOCR : http://127.0.0.1:8010/health
echo [RITA] API       : http://127.0.0.1:8000/docs
echo [RITA] Attendre le message "Ready" de PaddleOCR avant le premier test.
pause
