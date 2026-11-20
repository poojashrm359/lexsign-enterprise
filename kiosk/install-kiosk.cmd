@echo off
rem =====================================================================
rem  LexSign kiosk installer - run ONCE on the player, logged in as the
rem  account that auto-logs in at boot. Right-click, "Run as administrator".
rem =====================================================================
set "TARGET=C:\Tools\LexSign"
if not exist "%TARGET%" mkdir "%TARGET%"
copy /y "%~dp0lexsign-kiosk.cmd" "%TARGET%\lexsign-kiosk.cmd" >nul

rem Shortcut in the Startup folder: launcher starts (minimised) at every logon
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\LexSign Kiosk.lnk'); $s.TargetPath='%TARGET%\lexsign-kiosk.cmd'; $s.WorkingDirectory='%TARGET%'; $s.WindowStyle=7; $s.Save()"

rem Screen must never sleep or switch off
powercfg /change monitor-timeout-ac 0
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0

echo.
echo Installed to %TARGET%
echo 1. Edit %TARGET%\lexsign-kiosk.cmd  (SERVER_URL, SCREEN, ROTATE)
echo 2. Reboot the player. The display opens full screen automatically.
echo    Alt+F4 closes it; it reopens after 5 seconds. Stop it from Task Manager if needed.
echo.
pause
