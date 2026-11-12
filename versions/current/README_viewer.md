# V19.81 实时查看器

配套 SageMotion Hub App：`1_19_81vibrant`，build `901810`。

本查看器参考 V19.9 查看器的角度图、目标线、震动命令标记和连接状态界面，并按 V19.81 的指标字段进行了适配。它只通过 Hub WebSocket 读取 App 指标，不直接连接 IMU 或 `feedback_min`，也不会发送震动命令。

## 启动

需要 Python 3、Tkinter 和 `websocket-client`。启动器优先使用 `C:\Python39\python.exe`；如果该解释器存在，请在它里面安装依赖：

```powershell
& 'C:\Python39\python.exe' -m pip install websocket-client
```

若没有 `C:\Python39\python.exe`，则使用 `python -m pip install websocket-client`。

双击 `start_v19_81_viewer.cmd` 启动。默认 Hub 地址为 `192.168.137.1`；也可以从命令行指定其他地址：

```powershell
python .\fast_imu_training_viewer_v19.81.py --hub-ip 192.168.137.2
```

查看器默认每秒重绘 10 次，并只订阅图表和状态栏使用的 27 项 App 指标。静态站立状态栏显示校准状态、稳定计时、最大姿态偏差和重置次数。降低重绘频率只减少电脑绘图负担；Hub 到电脑的 WebSocket 数据频率仍由 Hub/App 决定。

## 显示说明

- 蓝线：当前训练腿的有符号髋后伸角度。
- 绿线：当前自适应目标。
- 红点：App 记录到的震动命令事件。
- 状态栏显示当前角度、目标、能力评估状态和震动命令统计。

V19.81 将 `feedback_min` 配置为独立反馈节点，不采集它的振动加速度。因此红点代表 App 发出的命令事件，不是电机实际震动的测量确认。
