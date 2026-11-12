# IMU Hip Extension Feedback V19.81vibrant

SageMotion Hub App version: `1_19_81vibrant`; build: **901810**.

**Change summary:** V19.81 separates the command-only `feedback_min` node from the three streamed posture sensors and switches to the `feedback_vibration_on/off` API. The hip-angle closed-loop and adaptive target logic remain unchanged. See the [V19.8 → V19.81 change log](CHANGELOG.md) for the full comparison.

## Downloads

- Import [IMU_Hip_Extension_Feedback_v1_19_81vibrant.zip](IMU_Hip_Extension_Feedback_v1_19_81vibrant.zip) into the Hub.
- Extract [Fast_IMU_Training_Viewer_v19_81.zip](Fast_IMU_Training_Viewer_v19_81.zip) on the Windows computer and run `start_v19_81_viewer.cmd`.
- Browse [App_Source/](App_Source/) to read the individual App files.

## Hub setup

Assign `right_thigh`, `left_thigh`, and `pelvis` to the **sensors** list. Assign `feedback_min` to the separate **feedback** list. Do not bind the physical feedback node as a sensor as well. The Hub SDK must provide `feedback_vibration_on()` and `feedback_vibration_off()`.

## What changed from V19.8

| Area | V19.8 | V19.81 |
|---|---|---|
| App version / build | `1_19_8vibrant` / `901800` | `1_19_81vibrant` / `901810` |
| Streamed nodes | Three posture IMUs plus `vibration_monitor` | Three posture IMUs only |
| Feedback list | Empty | `feedback_min` |
| Vibration API | `sensor_vibration_on/off()` | `feedback_vibration_on/off()` |

The feedback node receives vibration commands only; it is not streamed as a sensor. Command timestamps, duration, strength, state, and error counters describe App requests. They do not measure or confirm the motor's physical response. Feedback-node acceleration, RMS, and command/measured pairing are unavailable; the retained measurement fields are invalid placeholders (`vibration_monitor_valid=0`, quality `6`).

## Training behavior retained

Hip-angle calculation, the closed-loop target condition, one reward pulse per qualifying extension cycle, re-trigger gating, and adaptive target updates are retained from V19.8. The default reward remains **0.2 seconds at strength 2**, with a **0.25-second software duration cap**.

## Viewer

The Windows viewer subscribes to 27 App metrics. It displays hip angle, target, vibration command events, and standing-calibration state, stable elapsed time, posture deviation, and reset count. It receives App telemetry and Hub status over WebSocket only; it does not connect to the IMUs or feedback node and cannot control vibration. See [viewer instructions](README_viewer.md).

## Viewer environment

Requires Python 3, Tkinter, and `websocket-client`. The launcher first uses `C:\Python39\python.exe` if available, otherwise `python` on PATH. Default Hub IP: `192.168.137.1`; WebSocket: `5678`; status API: `80`.

No V19.81 hardware validation or offline test run is claimed in this release. See the [full change log](CHANGELOG.md).
