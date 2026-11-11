@echo off
rem OoT Remake Mods: opens the Mods window. (With Python installed, "OoT Mods.pyw" opens by itself too.)
setlocal
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -3 "%~dp0OoT Mods.pyw" & exit /b)
where pythonw >nul 2>nul && (start "" pythonw "%~dp0OoT Mods.pyw" & exit /b)
echo OoT Mods needs Python 3.8 or newer. The installer from python.org brings everything it uses:
echo     https://www.python.org/downloads/
echo Install it, then open this file again.
echo.
pause
