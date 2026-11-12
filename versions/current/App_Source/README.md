# IMU Hip Extension Feedback V19.81vibrant

更新日期：2026-11-12。SageMotion App 版本：1_19_81vibrant，build 901810。

## 本版改动

- 以 V19.8 为基础，保留髋关节后伸角度闭环、奖励短震触发、周期重新触发门控，以及训练目标的自适应更新。
- 三颗姿态 IMU 通过 sensors 持续采集：right_thigh、left_thigh、pelvis。
- 原 feedback_min 节点单独配置在 feedback 中。震动启停改用 feedback_vibration_on() 和 feedback_vibration_off()，不再将该节点作为第四颗传感器读取。
- 保留振动命令的请求时间、时长、强度和错误计数。分离配置后不再采集执行器的加速度/RMS，因此这些记录不能证明电机实际启动或停止，也不提供振动实测配对结果。
- vibration_monitor_valid 固定为 0、vibration_monitor_quality 为 6，表示本版本未从 feedback 节点采集振动信号。

## 导入与连接

1. 停止旧 Hub App，导入 IMU_Hip_Extension_Feedback_v1_19_81vibrant.zip。
2. 在 sensors 中连接 right_thigh、left_thigh、pelvis 三颗姿态 IMU。
3. 在 feedback 中连接原 feedback_min 执行器节点。不要把同一 MAC 同时配成 sensor 和 feedback；不需要新增硬件。
4. 启用反馈并设置训练腿、目标和保存位置。Hub SDK 必须支持 feedback_vibration_on/off。
5. 核对 App 版本 1_19_81vibrant 和描述中的 build 901810。

## 闭环训练逻辑

髋角度仍由三颗姿态 IMU 实时更新。达到目标角度并通过连续样本判定后，每个后伸周期触发一次短震；回到中立区并满足重新触发等待时间后，才允许下一次奖励。训练目标仍按有效后伸片段的表现自适应更新。此版本只改变执行器节点的配置和 SDK 启停接口，不改髋角度计算、闭环触发条件或目标更新规则。

默认奖励短震为 0.2 秒、强度 2，软件请求上限为 0.25 秒。能力评估和训练窗口参数沿用 V19.8 配置；具体值以 Hub 当前设置为准。

## 记录说明

命令事件表示程序调用反馈 API 的时刻，不等于设备确认或电机实测。由于 feedback 节点不在 sensors 流中，V19.81 不输出有效的振动加速度、RMS、传感器时间或命令/实测配对结果。旧测量字段保留为无效占位以兼容记录结构，请以 vibration_monitor_valid 和 vibration_monitor_quality 判别。
