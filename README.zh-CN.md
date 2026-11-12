# IMU 髋关节后伸训练与反馈

当前正式版本为 SageMotion Hub 上运行的 **V19.81 App**，并配有只读 Windows 实时查看器。

**下载：**[Hub App ZIP](versions/current/IMU_Hip_Extension_Feedback_v1_19_81vibrant.zip) · [Windows 查看器 ZIP](versions/current/Fast_IMU_Training_Viewer_v19_81.zip)

[English](README.md) | **简体中文**

## V19.81 配置

App 通过三颗姿态传感器采集数据：`right_thigh`、`left_thigh` 和 `pelvis`。请在 Hub 的 **feedback 列表**中单独配置 `feedback_min`。不要把它加入 sensors，也不要把同一颗实体节点同时分配到两个列表。

V19.81 使用 `feedback_vibration_on()` 和 `feedback_vibration_off()` 控制震动，保留 V19.8 的髋角闭环奖励触发与自适应目标更新逻辑。feedback 节点只接收震动命令；App 不会读取该节点的加速度数据。

查看器通过 WebSocket 读取 App 指标和 Hub 状态，不直接连接 IMU 或 `feedback_min`，也不会发送震动命令。界面显示髋后伸角、目标、命令事件和静态站立校准状态。命令事件代表 App 发出过震动请求，不代表电机的物理响应已经确认。V19.81 不包含 feedback 节点的震动实测。

## 快速开始

1. 将 Hub App ZIP 导入 SageMotion Hub，选择 **IMU Hip Extension Feedback V19.81vibrant**；App 版本为 `1_19_81vibrant`，build 为 **901810**。
2. 在 **sensors** 中配置 `right_thigh`、`left_thigh` 和 `pelvis`；在 **feedback** 中配置 `feedback_min`。
3. 设置训练腿、反馈开关、试次名称和保存位置。
4. 在 Windows 电脑上解压查看器 ZIP，运行 `start_v19_81_viewer.cmd`。
5. 在 Hub 页面启动 App，并根据查看器显示完成校准、评估和训练。

Hub SDK 必须支持 `feedback_vibration_on()` 和 `feedback_vibration_off()`。

## 查看器环境

查看器需要 Python 3、Tkinter 和 `websocket-client`。启动脚本先尝试 `C:\Python39\python.exe`，否则使用 PATH 中的 `python`。默认 Hub 地址为 `192.168.137.1`，WebSocket 端口为 `5678`，状态 API 端口为 `80`。

在启动查看器实际使用的 Python 环境中安装依赖：

```powershell
python -m pip install websocket-client
```

## 源码与版本历史

- [当前 V19.81 安装包、源码和说明](versions/current/)。
- [旧版 V19.7 安装包](versions/v19.7/)。
- [V19.9v 实验候选版](probably-solve/v19.9v/)，仍需实机验证。
- 当前文件统一放在稳定的 `versions/current/` 路径。先前 V19.8 的文件可通过 Git 历史查看。

本次发布未声称完成 V19.81 实机验证或离线测试；V19.8 的测试结果不适用于 V19.81。

[仓库许可证](LICENSE.md)
