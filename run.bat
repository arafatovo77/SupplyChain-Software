@echo off
title Supply Chain Management System
echo =======================================================
echo    Starting Supply Chain Management Web Software
echo =======================================================
echo.
echo Installing dependencies (if needed)...
pip install -r requirements.txt
echo.
echo Launching Server...
echo Open your browser at: http://127.0.0.1:5000
echo Default Login: admin / admin2201
echo Report Password: 2201
echo.
python app.py
pause
