# V19.8 IMU Hip Extension Viewer

版本：19.8，build 901800。配套 Hub App：1_19_8vibrant。

双击 `開啟V19_8vibrant查看器.cmd` 或 `start_v19_8_viewer.cmd`。
默认连接 192.168.137.1，WebSocket 5678，状态 API 80。
查看器启动后，在 Hub 页面启动 App，保持自然站立完成校准，再开始行走。

蓝线表示有符号髋后伸角度，绿线表示当前目标；状态栏显示查看器版本和 Hub 当前 App 的 version_id。
校准、等待启动、无效姿态和采集断流均有对应提示。连接断开后会重连，App 重启后会重新订阅。

运行环境需要 Python 3、Tkinter 和 `websocket-client`。启动脚本优先使用本机 C:\Python39\python.exe，否则使用 PATH 中的 python。
缺少依赖时，请在实际运行的 Python 环境安装 `websocket-client`，例如：

```powershell
& 'C:\Python39\python.exe' -m pip install websocket-client
```

指定其他 Hub IP：

```powershell
.\start_v19_8_viewer.cmd --hub-ip 192.168.137.2
```

检查版本：

```powershell
.\start_v19_8_viewer.cmd --version
```

若 Hub 日志持续报告 `Sensor data packet numbers have diverged beyond recovery` 和 `Fail to fetch sensor data`，请停止 App、重启并重新连接传感器；仍无法恢复时重启 Hub。查看器重新订阅不能恢复 Hub 驱动内部的同步缓存。

查看器只接收数据和读取运行状态；启动、停止和设备连接操作通过 Hub 页面完成。
