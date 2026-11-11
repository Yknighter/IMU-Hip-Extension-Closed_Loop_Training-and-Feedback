# V19.9v — probably solve

**候选方案，等待实机验证。** App 版本 `1_19_9vibrant`，build **901900**。38 项离线测试通过，尚不能宣称节点无线掉线、驱动失同步或电机实际时序已经修复。

## 下载与阅读源码

- [下载用户提供的完整源码 ZIP](IMU_Hip_Extension_Feedback_v19_9v_Source.zip?raw=true)：原文件逐字节保留。
- [直接浏览 App 源码](IMU_Hip_Extension_Feedback_v1_19_9vibrant/) · [缺帧检测模块](IMU_Hip_Extension_Feedback_v1_19_9vibrant/frame_guard.py) · [控制逻辑](IMU_Hip_Extension_Feedback_v1_19_9vibrant/core.py)。
- [查看器源码](fast_imu_training_viewer_v19_9.py) · [回放测试](verification/test_v19_9_gap_protection.py) · [完整说明](IMU_Hip_Extension_Feedback_v1_19_9vibrant/README.md)。
- [Hub App 导入 ZIP](IMU_Hip_Extension_Feedback_v1_19_9vibrant.zip?raw=true)：上传到 Hub。
- [电脑查看器 ZIP](Fast_IMU_Training_Viewer_v19_9.zip?raw=true)：在电脑解压后运行 `start_v19_9_viewer.cmd`。

`ARCHIVE_SHA256SUMS` 校验三个 ZIP；原包的 `SHA256SUMS` 校验解包后的源码文件。App 与查看器安装包的内容已与此源码包逐个比对。

## 本候选版的实际行为

- 检测到缺帧、重复、无效姿态或过期数据时，取消当前动作的达标累计，暂停新震动奖励，并尝试停止当前震动。
- **被拒绝的帧会跳过角度更新。** 恢复到有效、新鲜数据后，角度继续计算和记录；反馈需要等待新滤波窗口及连续 200 ms 中立位重新就绪。
- 恢复时即使角度已超过目标，也不补发旧奖励；下一次动作重新要求连续达标 30 ms。
- 已完成的训练统计及目标保留。能采集到的震动监测数据与命令记录仍保存，不是删除震动数据。
- **本版尚未实现“前三颗 IMU 正常就始终计算角度、第四颗异常只关闭震动”的独立控制架构。** 四路同步驱动停采时，也无法产生新的实时角度。
- 数据滞后阈值等为工程初始值；未加入并发 SDK 停震线程。断连后的物理停震需要核实节点固件行为。

## 离线检查

在本目录运行，需 Python、NumPy、SciPy 和 Tkinter：

```powershell
python -B -m unittest discover -s verification -p 'test_v19_9_*.py' -v
```

38 项检查覆盖达标 20 ms 后缺帧、恢复高角度不补发、中立位 200 ms 只计一次、恢复期间再次缺帧、缓存回放、重复包、时钟回绕、计算滞后、字段类型及曲线断点。测试使用模拟 SDK，不发送硬件命令。

查看器连接需要在实际运行的 Python 环境安装 `websocket-client`。更多启动说明见 [查看器说明](README_v19_9_viewer.md)。
