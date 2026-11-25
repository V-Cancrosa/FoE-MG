@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
echo Tworze srodowisko Pythona w .venv ...
%PY% -m venv .venv || (echo Nie znalazlem Pythona. Zainstaluj go z python.org i zaznacz "Add python.exe to PATH". & pause & exit /b 1)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt || (pause & exit /b 1)
echo.
set /p GPU=Masz karte NVIDIA i chcesz liczyc na niej (duzo szybciej)? [t/N] 
if /i "%GPU%"=="t" .venv\Scripts\python -m pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"
echo.
echo Gotowe. Sprawdz urzadzenia: nagrywaj.bat --lista
pause
