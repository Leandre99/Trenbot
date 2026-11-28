@echo off
rem Double-clic : met TrenBot a jour dans MT5 (telechargement depuis GitHub + compilation).
rem Garde ce fichier sur le Bureau du serveur.
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; $p=Join-Path $env:TEMP 'maj-trenbot.ps1'; Invoke-WebRequest 'https://raw.githubusercontent.com/Leandre99/Trenbot/main/mt5/maj-trenbot.ps1' -OutFile $p -UseBasicParsing; & $p"
echo.
pause
