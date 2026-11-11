# IMU Hip Extension Feedback v19.8

Hub App version: `1_19_8vibrant`; build **901800**.

## Download and run

- Import [IMU_Hip_Extension_Feedback_v1_19_8vibrant.zip](IMU_Hip_Extension_Feedback_v1_19_8vibrant.zip) into the SageMotion Hub.
- Extract [Fast_IMU_Training_Viewer_v19_8.zip](Fast_IMU_Training_Viewer_v19_8.zip) on the Windows computer. Run `start_v19_8_viewer.cmd`.
- The viewer ZIP is a desktop program, not a Hub App import package.
- Browse [IMU_Hip_Extension_Feedback_v1_19_8vibrant/](IMU_Hip_Extension_Feedback_v1_19_8vibrant/) for the matching App source and App README.

The viewer needs Python 3, Tkinter and `websocket-client`. The Windows launcher first tries `C:\Python39\python.exe`, then `python` on PATH. Default Hub IP: `192.168.137.1`; WebSocket port: `5678`; status API port: `80`.

## Recording and connection behavior

Trial recording defaults to CSV with 155 dynamic user fields. Fixed settings and duplicate telemetry are omitted from per-frame output. Both versions include the float-type fixes and viewer reconnect, calibration and stalled-stream messages. Four synchronized sensing nodes are required: `right_thigh`, `left_thigh`, `pelvis`, and `vibration_monitor`.

A node losing data can stop the complete synchronized stream. The viewer reconnects and renews subscriptions, but cannot repair a Hub driver or wireless-node failure. Neither version claims to fix the observed sensor-3 dropout.

## Offline validation

From this directory, run:

```powershell
python -B -m unittest discover -s verification -p "test_v19_8_*.py" -v
```

The 15 checks cover all recorded field types, save/stream consistency, real-shaped packets, reconnection, trial restart, calibration/stalled-stream prompts, and Tk curve rendering. Recording tests require NumPy and SciPy. These are offline checks, not physical Hub or motor certification.

`SHA256SUMS` lists file checksums. Device logs, participant recordings and local temporary files are excluded.
