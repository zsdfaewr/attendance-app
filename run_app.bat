@echo off
title Smart Attendance System Launcher
color 0a

echo [1/2] Starting Flask Local Server...
start cmd /k "cd /d C:\Users\toras\OneDrive\Desktop\attendance_app && python app.py"

echo [2/2] Starting Ngrok Tunnel for Mobile Access...
start cmd /k "ngrok http 5000"

echo All services launched successfully! You can close this window.
pause