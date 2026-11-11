# IMU Hip Extension Feedback

SageMotion Hub Apps and a Windows live viewer for hip-extension training. The current packages record synchronized IMU data to CSV and show the hip-extension angle, training target and feedback events.

**English** | [简体中文](README.zh-CN.md)

**Read App source online:** [v19.8 source files](versions/v19.8/IMU_Hip_Extension_Feedback_v1_19_8vibrant/) · [v19.7 source files](versions/v19.7/IMU_Hip_Extension_Feedback_v1_19_7vibrant/)

Both App directories contain the individual Python modules, JSON configuration, README and supporting files. Open a directory to read or review the code directly on GitHub.

**Experimental candidate:** [v19.9v — probably solve: source, packages and limitations](probably-solve/v19.9v/). Awaiting hardware validation; this does not claim to fix wireless dropouts.

[Download](#download) · [Quick start](#quick-start) · [Troubleshooting](#troubleshooting) · [Source and documentation](#source-and-documentation)

## Download

### v19.8 — current regular package

App version `1_19_8vibrant` · build **901800**

- **For the Hub:** [Download the v19.8 App ZIP](https://github.com/Yknighter/wenfeng/raw/refs/heads/main/versions/v19.8/IMU_Hip_Extension_Feedback_v1_19_8vibrant.zip).
- **For the Windows computer:** [Download the v19.8 viewer ZIP](https://github.com/Yknighter/wenfeng/raw/refs/heads/main/versions/v19.8/Fast_IMU_Training_Viewer_v19_8.zip).
- **Instructions:** [App guide (PDF)](versions/v19.8/IMU_Hip_Extension_Feedback_v1_19_8vibrant/Hip%20Extension%20App%20Guide.pdf) · [App details](versions/v19.8/IMU_Hip_Extension_Feedback_v1_19_8vibrant/README.md) · [All v19.8 files](versions/v19.8/).

> Download both ZIPs. Import the **App ZIP into the Hub**. Extract the **viewer ZIP on the computer** and run its launcher.

<details>
<summary>Need v19.7? Open the previous-version downloads.</summary>

App version `1_19_7vibrant` · build **901701**

- [Download the v19.7 Hub App ZIP](https://github.com/Yknighter/wenfeng/raw/refs/heads/main/versions/v19.7/IMU_Hip_Extension_Feedback_v1_19_7vibrant.zip).
- [Download the v19.7 Windows viewer ZIP](https://github.com/Yknighter/wenfeng/raw/refs/heads/main/versions/v19.7/Fast_IMU_Training_Viewer_v19_7.zip).
- [App details](versions/v19.7/IMU_Hip_Extension_Feedback_v1_19_7vibrant/README.md) · [All v19.7 files](versions/v19.7/).

Run `start_v19_7_viewer.cmd` after extracting the viewer ZIP. The PDF inside the historical v19.7 App package has older version labels; use its App README for the matching instructions.

</details>

Both versions include CSV saving, 155 dynamic user fields, float-field corrections, and viewer calibration, reconnect and stalled-stream messages. v19.8 adds synchronized version labels, the active Hub version in the viewer status bar, and an updated PDF guide.

## Quick start

The steps below use v19.8. You need a SageMotion Hub, four IMU/Dot nodes, a connected Windows computer, and a Hub SDK with `sensor_vibration_on()` and `sensor_vibration_off()` support.

1. **Download the two v19.8 ZIPs above.** Stop the old Hub App, then import `IMU_Hip_Extension_Feedback_v1_19_8vibrant.zip` through the Hub page. Select **IMU Hip Extension Feedback V19_8vibrant** and check build **901800** in its description.
2. **Assign the four sensing nodes in this order:** `right_thigh`, `left_thigh`, `pelvis`, `vibration_monitor`. The fourth node is the existing vibration node, now also recording acceleration. The separate feedback list is empty; assign each physical node once.
3. **Set Training Leg, Feedback Enabled, trial name and save location.** Recording defaults to CSV. See [the App instructions](versions/v19.8/IMU_Hip_Extension_Feedback_v1_19_8vibrant/README.md) for settings and feedback rules.
4. **Extract the viewer ZIP into one folder.** Double-click `start_v19_8_viewer.cmd` or `開啟V19_8vibrant查看器.cmd`. Check that the window title shows **V19.8**. If Python or a dependency is missing, follow [Viewer setup](#viewer-setup).
5. **Click Start on the Hub page.** Stand naturally until posture has been stable for 2 seconds and calibration finishes. Then walk naturally for the default 60-second assessment; training follows automatically. The viewer shows the current stage.

### What the viewer shows

- **Blue line:** signed hip-extension angle; positive values represent extension.
- **Green line:** current training target.
- **Red dots:** recorded vibration command events, not a measurement of physical motor response.
- **Top message and bottom status:** calibration, assessment, connection state, stale data, viewer version and active Hub App version ID.

The viewer receives data and reads Hub status. Start, stop and node connection controls remain on the Hub page.

## Viewer setup

The viewer needs **Python 3 with Tkinter** and **`websocket-client`**. The Windows launcher first tries `C:\Python39\python.exe`, then `python` on PATH. Install the dependency in the interpreter that runs the viewer.

From the extracted viewer folder, with Python on PATH:

```powershell
python -m pip install websocket-client
python fast_imu_training_viewer_v19_8.py --hub-ip 192.168.137.1
```

If the launcher uses `C:\Python39\python.exe`, install into that environment:

```powershell
& 'C:\Python39\python.exe' -m pip install websocket-client
```

Defaults: Hub IP **192.168.137.1**, WebSocket **5678**, status API **80**. To use another Hub address:

```powershell
.\start_v19_8_viewer.cmd --hub-ip 192.168.137.2
```

## Troubleshooting

- **The window opens but has no curves:** check the top message. `READY` or `CONFIGURE` means the Hub App has not started collecting. Complete setup and click Start; check sensor connections if the viewer reports invalid posture data.
- **The App stops or curves stop updating:** check the Hub log. A sensor-3 timeout or `Fail to fetch sensor data` means the synchronized acquisition has lost node data. Sensor 3 is `vibration_monitor` in this configuration. Stop the App, check and reconnect that node; restart the nodes or Hub if needed. Viewer reconnection cannot restore a failed driver stream. Sensor-3 dropouts observed during testing remain unresolved in these packages.
- **The Hub rejects a ZIP:** import the `IMU_Hip_Extension_Feedback_...zip` App package. The `Fast_IMU_Training_Viewer_...zip` package runs on the computer.
- **`No module named websocket`:** install `websocket-client` in the Python environment used by the launcher; see [Viewer setup](#viewer-setup).

## Source and documentation

- [v19.8 source, packages and tests](versions/v19.8/) · [v19.7 source, packages and tests](versions/v19.7/).
- [Version index](versions/README.md) · [Viewer details](versions/v19.8/README_v19_8_viewer.md) · [Recording fields and feedback rules](versions/v19.8/IMU_Hip_Extension_Feedback_v1_19_8vibrant/README.md).
- Each version includes `SHA256SUMS` for download verification and its own `verification/` directory. **14 v19.7 checks and 15 v19.8 checks passed**, covering recording types, stream parsing, reconnection and Tk curve rendering. These are offline results; they do not establish physical motor timing or wireless stability.
- The root-level App files belong to **legacy v1.4.1**. Use `versions/` for the current packages. [Archived v1.4.1 documentation](docs/legacy-v1.4.1.md).
- [SageMotion Python API documentation](https://docs.sagemotion.com/app_writing/python-api).

## Project credits

- **Author:** Yknighter
- **Supervisor:** Dr. Wai-Hang Kwong
- **Affiliation:** Department of Rehabilitation Sciences, The Hong Kong Polytechnic University
- **Laboratory:** Gait Analysis Laboratory

[Repository license](LICENSE.md)
