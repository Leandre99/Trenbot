@echo off
rem Double-clic : ouvre le tableau de bord de trendbot dans ton navigateur (MT5 ouvert, de preference connecte a ta demo).
rem Garde cette fenetre noire ouverte tant que tu utilises le tableau de bord.
cd /d "%~dp0"
python dashboard.py
pause
