@echo off
rem Szuka Pythona 3.12 (albo 3.13/3.11), w razie potrzeby go instaluje, potem otwiera okno instalatora.
rem Nowsze wersje (3.14+) odpadaja: onnxruntime/ctranslate2 nie maja jeszcze dla nich paczek.
chcp 65001 >nul
cd /d "%~dp0"
title Sesja - instalacja
set "PYW="

echo Szukam Pythona 3.12 ...
call :szukaj
if not defined PYW call :zainstaluj
if not defined PYW (
  echo.
  echo Nie udalo sie zainstalowac Pythona 3.12 automatycznie.
  echo Pobierz "Windows installer 64-bit" ze strony, ktora sie otworzy,
  echo zainstaluj go i uruchom instaluj.bat jeszcze raz.
  start "" "https://www.python.org/downloads/release/python-31210/"
  pause
  exit /b 1
)
echo Python: %PYW%
echo Otwieram okno instalatora...
start "" "%PYW%" "%~dp0Instalator.pyw"
exit /b 0


:szukaj
rem 1) launcher "py" (stary albo nowy Python install manager); <nul, zeby nic nie pytalo
for %%V in (3.12 3.13 3.11) do (
  if not defined PYW (
    for /f "usebackq delims=" %%P in (`py -%%V -c "import sys,os;print(os.path.join(sys.base_prefix,'pythonw.exe'))" 2^>nul ^<nul`) do set "PYW=%%P"
  )
)
rem 2) typowe miejsca instalacji (swiezo zainstalowany Python nie jest jeszcze w PATH)
for %%D in ("%LOCALAPPDATA%\Python\pythoncore-3.12-64" "%LOCALAPPDATA%\Programs\Python\Python312" "%ProgramFiles%\Python312") do (
  if not defined PYW if exist "%%~D\pythonw.exe" set "PYW=%%~D\pythonw.exe"
)
if defined PYW if not exist "%PYW%" set "PYW="
exit /b 0


:zainstaluj
echo Nie ma Pythona 3.12 - instaluje go (kilka minut, nie zamykaj okna).
rem Nowy "Python install manager" (to on pokazywal aliasy w Ustawieniach) ma polecenie "py install"
py list >nul 2>nul <nul
if not errorlevel 1 (
  py install --yes 3.12 || py install 3.12
  call :szukaj
)
if defined PYW exit /b 0
where winget >nul 2>nul
if not errorlevel 1 (
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  call :szukaj
)
exit /b 0
