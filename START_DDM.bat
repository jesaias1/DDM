@echo off
REM Dobbeltklik denne fil for at starte Den Danske Metode.
REM Den aabner serveren i sit eget vindue og din browser paa login-siden.
cd /d "%~dp0"

echo Starter Den Danske Metode...
start "Den Danske Metode - server (luk ikke dette vindue)" powershell -ExecutionPolicy Bypass -NoExit -File "%~dp0START_DDM.ps1"

echo Venter paa at serveren er klar...
timeout /t 9 /nobreak >nul

echo Aabner browseren paa http://127.0.0.1:5000
start "" "http://127.0.0.1:5000"

echo.
echo FAERDIG. Login: jesaias / miebs112
echo Lad server-vinduet vaere aabent mens du bruger appen.
echo (Luk server-vinduet for at stoppe.)
timeout /t 6 /nobreak >nul
