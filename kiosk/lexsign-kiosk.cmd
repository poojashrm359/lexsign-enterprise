@echo off
rem =====================================================================
rem  LexSign kiosk launcher  -  edit these three lines for each screen
rem =====================================================================
set SERVER_URL=http://10.215.95.165:8000
set SCREEN=court-1
set ROTATE=90
rem  SCREEN : court-1 .. court-4  or  master-1 .. master-4
rem  ROTATE : 90 (clockwise), 270 (anti-clockwise) or 0 when Windows itself is set to Portrait
rem =====================================================================

set URL=%SERVER_URL%/display/%SCREEN%
if not "%ROTATE%"=="0" set URL=%URL%?rotate=%ROTATE%

set BROWSER=
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if "%BROWSER%"=="" if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if "%BROWSER%"=="" if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if "%BROWSER%"=="" if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if "%BROWSER%"=="" (
    echo No Chrome or Edge found on this player. Install one and run again.
    pause
    exit /b 1
)

rem Separate browser profile so no "restore pages" prompts and no interference with normal browsing
set "PROFILE=%LOCALAPPDATA%\LexSignKiosk"

:wait
rem Do not open the browser until the LexSign server answers (network comes up after logon)
curl -s -o nul --max-time 3 "%SERVER_URL%/api/benches" && goto launch
echo Waiting for LexSign server at %SERVER_URL% ...
timeout /t 5 /nobreak >nul
goto wait

:launch
echo Opening %URL%
start "" /wait "%BROWSER%" --kiosk --no-first-run --noerrdialogs --disable-infobars --disable-session-crashed-bubble --disable-pinch --overscroll-history-navigation=0 --autoplay-policy=no-user-gesture-required --user-data-dir="%PROFILE%" "%URL%"
rem Browser was closed or crashed: wait a moment and bring it back
timeout /t 5 /nobreak >nul
goto wait
