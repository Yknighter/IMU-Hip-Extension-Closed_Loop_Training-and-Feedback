# IMU Hip Extension Training and Feedback

The current release is **V19.81** for SageMotion Hub, with a read-only Windows live viewer.

**Downloads:** [Hub App ZIP](versions/current/IMU_Hip_Extension_Feedback_v1_19_81vibrant.zip) · [Windows viewer ZIP](versions/current/Fast_IMU_Training_Viewer_v19_81.zip)

[简体中文](README.zh-CN.md)

## V19.81 configuration

The App streams three posture sensors: `right_thigh`, `left_thigh`, and `pelvis`. Configure `feedback_min` separately in the Hub's **feedback** list. Do not add that node to the sensor list or assign the same physical node to both lists.

V19.81 calls `feedback_vibration_on()` and `feedback_vibration_off()` for vibration. It retains the hip-angle closed-loop reward trigger and adaptive target update logic from V19.8. The feedback node receives vibration commands; the App does not stream its accelerometer data.

The viewer reads App telemetry and Hub status over WebSocket. It does not connect directly to IMUs or `feedback_min`, and it does not send vibration commands. It displays the hip-extension angle, target, command events, and standing-calibration status. A recorded command event means the App requested a vibration; it does not confirm physical motor response. V19.81 has no feedback-node vibration measurement.

## Quick start

1. Import the Hub App ZIP and select **IMU Hip Extension Feedback V19.81vibrant** (App version `1_19_81vibrant`, build **901810**).
2. Assign `right_thigh`, `left_thigh`, and `pelvis` under **sensors**, and `feedback_min` under **feedback**.
3. Configure training leg, feedback, trial name, and save location.
4. Extract the viewer ZIP on the Windows computer and run `start_v19_81_viewer.cmd`.
5. Start the App on the Hub. Follow the viewer's calibration and training-stage status.

The Hub SDK must support `feedback_vibration_on()` and `feedback_vibration_off()`.

## Viewer setup

The viewer needs Python 3, Tkinter, and `websocket-client`. The launcher first tries `C:\Python39\python.exe`, then `python` on PATH. The default Hub address is `192.168.137.1`; WebSocket port is `5678`, and status API port is `80`.

Install the dependency in the Python environment used by the launcher:

```powershell
python -m pip install websocket-client
```

## Source and history

- [Current V19.81 package, source, and instructions](versions/current/).
- [Previous V19.7 package](versions/v19.7/).
- [Experimental V19.9v candidate](probably-solve/v19.9v/); it still requires hardware validation.
- The current files are kept under the stable `versions/current/` path. The previous V19.8 files remain available through Git history.

No V19.81 hardware validation or offline test run is claimed by this publication. The V19.8 verification results do not apply to V19.81.

[Repository license](LICENSE.md)
