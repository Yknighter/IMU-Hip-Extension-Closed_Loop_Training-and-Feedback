# V19.7 desktop viewer

Extract all files into one directory, then run `start_v19_7_viewer.cmd`. The Chinese-named launcher calls the same script.

Requires Python 3, Tkinter and `websocket-client`. The launcher uses `C:\Python39\python.exe` when present; otherwise it uses `python` on PATH.

Default Hub IP: 192.168.137.1. To override: `start_v19_7_viewer.cmd --hub-ip 192.168.137.2`. Start the Hub App from the Hub page; this viewer only receives data and reads App state.

Window title: V19.7 IMU Hip Extension Viewer. Blue: signed hip extension. Green: current target. Calibration and stream interruptions are shown above the chart.
