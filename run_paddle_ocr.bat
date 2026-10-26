@echo off
setlocal
cd /d %~dp0
rem Python 3.12 pour PaddleOCR. Surcharge possible : set PY312=C:\chemin\python.exe
if not defined PY312 set "PY312=%LOCALAPPDATA%\Python\pythoncore-3.12-64\python.exe"
if not exist "%PY312%" (
  echo [RITA] Python 3.12 introuvable : %PY312%
  echo [RITA] Definissez la variable PY312 avec le chemin de python.exe 3.12
  pause
  exit /b 1
)
"%PY312%" tools\paddle_ocr_service.py
