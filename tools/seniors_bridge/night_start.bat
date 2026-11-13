@echo off
rem ============================================================
rem  night_start.bat - nocturnal loop of the JAWL seniors bridge
rem  Retries every 10 min until the first cycle succeeds.
rem  On success (exit 0) it exits; further cycles are driven by the DSH agent.
rem ============================================================
setlocal
cd /d G:\AI\JAWL-VoiceCompanion-V0.5
echo [%date% %time%] night bridge loop started >> tools\seniors_bridge\night.log

:loop
python -u tools\seniors_bridge\connect_seniors.py >> tools\seniors_bridge\night.log 2>&1
if %ERRORLEVEL% EQU 2 (
    echo [%date% %time%] phase timeout - retry in 10 min >> tools\seniors_bridge\night.log
    timeout /t 600 /nobreak >nul
    goto loop
)
echo [%date% %time%] bridge finished, exit=%ERRORLEVEL% >> tools\seniors_bridge\night.log
endlocal
