@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 1/3 Python ===
set PY=python
where py >nul 2>nul && set PY=py -3
py -3.12 --version >nul 2>nul && set PY=py -3.12
%PY% -m venv .venv || (echo Nie znalazlem Pythona. Zainstaluj go z python.org i zaznacz "Add python.exe to PATH". & pause & exit /b 1)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt || (pause & exit /b 1)
echo.
set /p GPU=Masz karte NVIDIA i chcesz liczyc na niej (duzo szybciej)? [T/n] 
if /i not "%GPU%"=="n" .venv\Scripts\python -m pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"
echo.
echo === 2/3 Bot Discord (opcjonalnie) ===
where node >nul 2>nul
if errorlevel 1 (
  echo Brak Node.js - tryb bota bedzie niedostepny. Jesli go chcesz: zainstaluj Node.js LTS z nodejs.org i uruchom instaluj.bat jeszcze raz.
) else (
  pushd bot
  call npm install --omit=dev
  popd
)
echo.
echo === 3/3 Skrot na pulpicie ===
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Sesja.lnk'); $s.TargetPath='%~dp0.venv\Scripts\pythonw.exe'; $s.Arguments='\"%~dp0Sesja.pyw\"'; $s.WorkingDirectory='%~dp0'; $s.Description='Nagrywanie i transkrypcja sesji'; $s.Save()"
echo.
echo Gotowe. Na pulpicie jest skrot "Sesja" (albo uruchom start.bat).
pause
