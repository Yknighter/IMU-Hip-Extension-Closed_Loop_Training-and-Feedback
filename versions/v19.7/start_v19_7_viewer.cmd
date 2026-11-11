@echo off
title V19.7 IMU Hip Extension Viewer
cd /d "%~dp0"
if exist "C:\Python39\python.exe" (
    "C:\Python39\python.exe" fast_imu_training_viewer.py --hub-ip 192.168.137.1 %*
) else (
    python fast_imu_training_viewer.py --hub-ip 192.168.137.1 %*
)
if errorlevel 1 pause
