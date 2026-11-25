@echo off
cd /d "%~dp0"
title MARPOL-SAFE Shipping Demo
if not exist ".venv\Scripts\python.exe" (
    echo Project environment not found. Follow the setup steps in README.md first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run app.py
pause
