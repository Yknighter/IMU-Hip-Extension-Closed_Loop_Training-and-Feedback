# IMU Hip Extension Feedback V19.81vibrant

SageMotion Hub App version: `1_19_81vibrant`; build: **901810**.

## Downloads

- Import [IMU_Hip_Extension_Feedback_v1_19_81vibrant.zip](IMU_Hip_Extension_Feedback_v1_19_81vibrant.zip) into the Hub.
- Extract [Fast_IMU_Training_Viewer_v19_81.zip](Fast_IMU_Training_Viewer_v19_81.zip) on the Windows computer and run `start_v19_81_viewer.cmd`.
- Browse [App_Source/](App_Source/) to read the individual App files.

## Hub setup

Assign `right_thigh`, `left_thigh`, and `pelvis` to the **sensors** list. Assign `feedback_min` to the separate **feedback** list. Do not bind the physical feedback node as a sensor as well. The Hub SDK must provide `feedback_vibration_on()` and `feedback_vibration_off()`.

## Behavior

The App continues to calculate hip extension from the three posture IMUs, issue a short vibration when the closed-loop target condition is met, and update the target adaptively. The vibration node handles commands only and is not streamed as a sensor.

The viewer receives telemetry and status over WebSocket. It does not connect to the IMUs or feedback node and cannot control vibration. Command events record App requests, not measured motor response. V19.81 does not include feedback-node acceleration or vibration RMS measurement.

## Viewer environment

Requires Python 3, Tkinter, and `websocket-client`. The launcher first uses `C:\Python39\python.exe` if available, otherwise `python` on PATH. Default Hub IP: `192.168.137.1`; WebSocket: `5678`; status API: `80`.

No V19.81 hardware validation or offline test run is claimed in this release.
