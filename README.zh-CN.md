# IMU 髋后伸训练与反馈

本项目包含在 SageMotion Hub 上运行的训练 App，以及在 Windows 电脑上运行的实时查看器。App 同步采集 IMU 数据、保存 CSV，并根据髋后伸目标发出震动命令；查看器显示角度、当前目标和反馈事件。

[English](README.md) | **简体中文**

**在线阅读 App 源码：**[v19.8 源码目录](versions/v19.8/IMU_Hip_Extension_Feedback_v1_19_8vibrant/) · [v19.7 源码目录](versions/v19.7/IMU_Hip_Extension_Feedback_v1_19_7vibrant/)

两个目录都已逐个上传 Python 模块、JSON 配置、README 及配套文件，点开即可在 GitHub 上直接阅读和审查代码。

**候选解决方案：**[v19.9v — probably solve：源码、安装包与限制](probably-solve/v19.9v/)。等待实机验证，尚不能宣称无线掉线问题已经解决。

[下载文件](#下载文件) · [开始使用](#开始使用) · [常见问题](#常见问题) · [源码与详细说明](#源码与详细说明)

## 下载文件

### v19.8：当前常规版本

App 版本：`1_19_8vibrant`；build：**901800**。

- **导入 Hub 的文件：**[下载 v19.8 App ZIP](https://github.com/Yknighter/wenfeng/raw/refs/heads/main/versions/v19.8/IMU_Hip_Extension_Feedback_v1_19_8vibrant.zip)。
- **在电脑上运行的文件：**[下载 v19.8 查看器 ZIP](https://github.com/Yknighter/wenfeng/raw/refs/heads/main/versions/v19.8/Fast_IMU_Training_Viewer_v19_8.zip)。
- **操作说明：**[PDF 指南](versions/v19.8/IMU_Hip_Extension_Feedback_v1_19_8vibrant/Hip%20Extension%20App%20Guide.pdf) · [App 详细说明](versions/v19.8/IMU_Hip_Extension_Feedback_v1_19_8vibrant/README.md) · [浏览 v19.8 全部文件](versions/v19.8/)。

> 两个 ZIP 都需要下载。**App ZIP 上传到 Hub；查看器 ZIP 在电脑上解压后运行。**

<details>
<summary>需要 v19.7？展开查看旧版下载。</summary>

App 版本：`1_19_7vibrant`；build：**901701**。

- [下载 v19.7 Hub App ZIP](https://github.com/Yknighter/wenfeng/raw/refs/heads/main/versions/v19.7/IMU_Hip_Extension_Feedback_v1_19_7vibrant.zip)。
- [下载 v19.7 电脑查看器 ZIP](https://github.com/Yknighter/wenfeng/raw/refs/heads/main/versions/v19.7/Fast_IMU_Training_Viewer_v19_7.zip)。
- [App 详细说明](versions/v19.7/IMU_Hip_Extension_Feedback_v1_19_7vibrant/README.md) · [浏览 v19.7 全部文件](versions/v19.7/)。

解压查看器后运行 `start_v19_7_viewer.cmd`。v19.7 导入包中的历史 PDF 仍带旧版标识，请以该版本的 App README 为准。

</details>

两个版本都采用 CSV 保存，保留 155 个动态用户字段，包含字段类型修正、校准提示、查看器重连和断流提示。v19.8 同步更新版本标识，在查看器状态栏显示 Hub 当前 App 的版本，并更新 PDF 指南。

## 开始使用

以下步骤以 v19.8 为例。准备 SageMotion Hub、四个 IMU/Dot 节点及与 Hub 连通的 Windows 电脑。Hub SDK 需要支持 `sensor_vibration_on()` 和 `sensor_vibration_off()`。

1. **下载上面的两个 v19.8 ZIP。** 停止旧 Hub App，导入 `IMU_Hip_Extension_Feedback_v1_19_8vibrant.zip`。选择 **IMU Hip Extension Feedback V19_8vibrant**，核对描述中的 build **901800**。
2. **按顺序绑定四个采集节点：**`right_thigh`、`left_thigh`、`pelvis`、`vibration_monitor`。第四个就是原有震动节点，现在同时记录加速度。独立 feedback 列表为空，同一颗节点只绑定一次。
3. **设置训练侧、是否启用反馈、试次名称和保存位置。** 默认保存为 CSV；参数及反馈规则见 [App 详细说明](versions/v19.8/IMU_Hip_Extension_Feedback_v1_19_8vibrant/README.md)。
4. **把查看器 ZIP 解压到同一文件夹。** 双击 `start_v19_8_viewer.cmd` 或 `開啟V19_8vibrant查看器.cmd`，确认窗口标题为 **V19.8**。缺少 Python 或依赖时，按下方“查看器环境”设置。
5. **在 Hub 页面点击 Start。** 先自然站立，连续稳定 2 秒完成校准，再自然行走进行默认 60 秒的能力评估，随后自动进入训练。查看器顶部会显示当前阶段。

### 画面怎么看

- **蓝线：**有符号髋后伸角度，正值表示后伸。
- **绿线：**当前训练目标。
- **红点：**记录到的震动命令事件，不等同于电机的物理响应实测。
- **顶部提示与底部状态：**校准、能力评估、连接及断流情况、查看器版本、Hub 当前 App 的版本标识。

查看器接收数据并读取 Hub 状态；启动、停止和节点连接在 Hub 页面操作。

## 查看器环境

需要 **Python 3、Tkinter 和 `websocket-client`**。启动脚本优先使用 `C:\Python39\python.exe`，否则使用 PATH 中的 `python`。依赖应安装到实际运行查看器的 Python 环境中。

如果 Python 已加入 PATH，在解压后的查看器目录运行：

```powershell
python -m pip install websocket-client
python fast_imu_training_viewer_v19_8.py --hub-ip 192.168.137.1
```

如果启动脚本使用 `C:\Python39\python.exe`，请安装到这个环境：

```powershell
& 'C:\Python39\python.exe' -m pip install websocket-client
```

默认 Hub IP 为 **192.168.137.1**，WebSocket 端口 **5678**，状态 API 端口 **80**。其他 IP 可以通过启动参数指定：

```powershell
.\start_v19_8_viewer.cmd --hub-ip 192.168.137.2
```

## 常见问题

- **窗口打开但没有曲线：**先看顶部提示。`READY` 或 `CONFIGURE` 表示 Hub App 尚未开始采集，完成配置后点击 Start；若显示姿态无效，检查姿态节点连接。
- **App 自动停止或曲线停止更新：**检查 Hub 日志。sensor 3 超时或持续 `Fail to fetch sensor data` 表示同步采集丢失了节点数据。当前配置中 sensor 3 是 `vibration_monitor`；先停止 App，检查并重新连接该节点，必要时重启节点或 Hub。查看器重连无法修复驱动断流，这两个版本尚未解决测试中观察到的 sensor 3 掉线问题。
- **Hub 无法导入 ZIP：**应导入 `IMU_Hip_Extension_Feedback_...zip`。`Fast_IMU_Training_Viewer_...zip` 应在电脑解压运行。
- **提示 `No module named websocket`：**在启动脚本实际使用的 Python 环境中安装 `websocket-client`，步骤见“查看器环境”。

## 源码与详细说明

- [v19.8 源码、安装包与测试](versions/v19.8/) · [v19.7 源码、安装包与测试](versions/v19.7/)。
- [版本索引](versions/README.md) · [查看器说明](versions/v19.8/README_v19_8_viewer.md) · [记录字段与反馈规则](versions/v19.8/IMU_Hip_Extension_Feedback_v1_19_8vibrant/README.md)。
- 每个版本包含文件校验清单 `SHA256SUMS` 和独立的 `verification/` 测试目录。**v19.7 的 14 项、v19.8 的 15 项离线检查已通过**，覆盖记录类型、推流解析、重连及 Tk 曲线绘制；这些结果不代表电机时序或无线稳定性已经完成实机验证。
- 仓库根目录的 App 文件属于 **v1.4.1 旧版**，当前版本请使用 `versions/` 下的文件。[旧版技术说明归档](docs/legacy-v1.4.1.md)。
- [SageMotion Python API 文档](https://docs.sagemotion.com/app_writing/python-api)。

## 项目信息

- **作者：**Yknighter
- **导师：**Dr. Wai-Hang Kwong
- **所属单位：**Department of Rehabilitation Sciences, The Hong Kong Polytechnic University
- **实验室：**Gait Analysis Laboratory

[仓库许可证](LICENSE.md)
