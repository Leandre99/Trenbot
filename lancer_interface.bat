@echo off
rem Double-clic : ouvre le tableau de bord de trendbot dans ton navigateur, SANS fenetre noire.
rem Pour tout arreter : menu du compte (en haut a droite de la page) puis Quitter trendbot.
rem MT5 doit etre ouvert, de preference connecte a ta demo.
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
  python dashboard.py
  pause
) else (
  start "" pythonw dashboard.py
)
