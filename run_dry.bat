@echo off
rem WallexB - one-click PAPER trading (safe: no real orders possible)
cd /d "%~dp0"
pip install -r requirements.txt >nul 2>&1
python -m wallexbot run %*
