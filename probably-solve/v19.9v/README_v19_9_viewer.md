# V19.9v 实时查看器

配套 Hub App：1_19_9vibrant，build 901900。

将查看器 ZIP 的全部文件解压至同一目录，然后双击 start_v19_9_viewer.cmd 或「開啟V19_9vibrant查看器.cmd」。App 的导入与启动在 Hub 页面完成。

需要 Python 3、Tkinter 和 websocket-client。脚本优先使用 C:\Python39\python.exe，否则使用 PATH 中的 python；请将依赖安装到实际运行的解释器中。

默认 Hub IP 192.168.137.1，WebSocket 5678，状态 API 80。指定其他 IP：

```powershell
.\start_v19_9_viewer.cmd --hub-ip 192.168.137.2
```

查看版本：`start_v19_9_viewer.cmd --version`。

蓝线为有符号后伸角度，绿线为当前目标，红点为震动命令事件。过期或无效数据不再绘制角度连线，缺口前后不会被直接连接。

红色提示表示数据缺口、过期或版本不匹配；橙色提示表示新数据已恢复，正在填满滤波窗口或等待中立位保持 200 ms。恢复时即使角度已经超过目标，也不补发奖励。

如果 Hub 因节点掉线自动停止，查看器无法自行修复驱动或重启 App，需要先在 Hub 恢复设备连接。本查看器只接收数据和读取运行状态。
