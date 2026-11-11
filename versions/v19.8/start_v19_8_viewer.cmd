@echo off
title V19.8 IMU Hip Extension Viewer
cd /d "%~dp0"
if exist "C:\Python39\python.exe" (
    "C:\Python39\python.exe" "%~dp0fast_imu_training_viewer_v19_8.py" --hub-ip 192.168.137.1 %*
) else (
    python "%~dp0fast_imu_training_viewer_v19_8.py" --hub-ip 192.168.137.1 %*
)
if errorlevel 1 pause
