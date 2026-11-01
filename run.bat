@echo off
title GPU VRAM Task Manager & Hardware Monitor
python main.py
if errorlevel 1 (
    echo.
    echo Error running application. Make sure dependencies are installed:
    echo pip install -r requirements.txt
    pause
)
