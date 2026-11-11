# V19.9v 发布文件

App 版本 1_19_9vibrant，build 901900。

- IMU_Hip_Extension_Feedback_v1_19_9vibrant.zip：Hub 导入包，25 个文件位于 ZIP 根目录。
- Fast_IMU_Training_Viewer_v19_9.zip：电脑查看器，解压后双击 start_v19_9_viewer.cmd。
- IMU_Hip_Extension_Feedback_v19_9v_Source.zip：完整源码、查看器、说明和离线测试，供阅读与开发；不作为 Hub 导入包。

App 源码在 [IMU_Hip_Extension_Feedback_v1_19_9vibrant](IMU_Hip_Extension_Feedback_v1_19_9vibrant/)，行为与默认工程参数见其中的 [README](IMU_Hip_Extension_Feedback_v1_19_9vibrant/README.md)。

本版在检测到缺帧、重复、无效姿态或旧数据时中断当前动作，不补发奖励。恢复后先填满新滤波窗口，回中立位保持 200 ms，再允许下一次连续达标 30 ms 的后伸奖励。完成的训练统计及目标保留。

38 项离线测试通过。在本目录运行：

```powershell
& 'C:\Python39\python.exe' -B -m unittest discover -s verification -p 'test_v19_9_*.py' -v
```

测试需要 NumPy、SciPy 和 Tkinter。查看器连接需要 websocket-client。测试使用模拟 SDK，不控制硬件；数据缺口判定初始值和物理震动仍需实机验证。
