# IMU Hip Extension Feedback V19_7vibrant

更新日期：2026-11-11。SageMotion App 版本：`1_19_7vibrant`，build `901701`。
训练记录默认保存为 CSV。逐帧数据保留随时间变化的角度、动态阈值、运行状态和事件；固定配置及重复字段不再逐行写入。

## 本版更新

- build 901701 修正自适应统计值和震动记录初始值的浮点类型，避免 Hub 逐帧报告类型不符。训练模式下 `adaptive_eval_target_phase_sec` 沿用历史字段名，数值仍表示有效片段计数，本次仅修正输出类型。
- 查看器在运行中断流时显示红色提示及传感器检查建议；自动重新订阅不能修复 Hub 驱动内部的同步故障。
- 改用 CSV 保存训练记录；逐帧数据仅保留随时间变化的信号、状态和事件，移除固定配置值及重复字段。

- 将现有反馈节点配为第四个采集节点 `vibration_monitor`，保存它自己的加速度及时间戳。
- 启动和停止只调用新版 `sensor_vibration_on()` / `sensor_vibration_off()`；无旧版回退。
- 分开记录命令、独立加速度 RMS、检测候选和配对状态；去除重复的逐帧停止调用。
- 删除旧震动 API 回退和未使用的旧震动函数。
- 更新程序、查看器、默认试次名称及随包 PDF 说明。
- Hub SDK 必须支持两个新版震动接口。

## 导入与启动

1. 停止原来的 Hub App，导入 `IMU_Hip_Extension_Feedback_v1_19_7vibrant.zip`。
2. 选择 **IMU Hip Extension Feedback V19_7vibrant**，核对版本 `1_19_7vibrant` 和 App 描述中的 build `901701`。Hub 可能自行生成 version_id，应以描述中的 build 区分此修订。
3. 指定 `right_thigh`、`left_thigh`、`pelvis` 三个姿态 IMU；原 `feedback_min` 那颗现有节点改配为第四个传感器 `vibration_monitor`。反馈列表为空，不要把同一 MAC 配对两次。不需要新增硬件。
4. 设置 Training Leg、Feedback Enabled、试次名称和保存位置。
5. 运行 `fast_imu_training_viewer.py`，或双击 `開啟V19_7vibrant查看器.cmd`。默认 Hub IP：`192.168.137.1`。
6. 启动 Hub App，保持自然站立，连续稳定 2 秒后开始 60 秒无震动能力评估；评估结束进入训练。

查看器和启动脚本放在本目录的上一级，不在 Hub 导入 ZIP 内。查看器按可用字段识别兼容性。

如果 App 仍显示 RUNNING，但日志出现 `Sensor data packet numbers have diverged beyond recovery`，随后持续 `Fail to fetch sensor data`，请停止 App，重启并重新连接传感器后再运行；仍无法恢复时重启 Hub。当前配置的 sensor 3 对应 `vibration_monitor`，应优先检查该节点。该故障发生在 Hub 采集驱动层，重开查看器无法恢复其同步缓存。

## 训练规则

后伸角度 E 为正、目标为 T。先在 E <= 0 保持 200 ms；随后 E >= T 连续 30 ms，发出一次奖励短震。
默认短震为 0.2 秒、强度 2；每次后伸最多一次，再回到 E <= 0 保持 200 ms 才能重新触发。
单次请求时长在软件中限制为不超过 0.25 秒；这是请求参数限制，不是电机实测时长保证。

能力评估使用有效后伸片段峰值的第 75 百分位，向下取整，默认限制为 1 至 15 度。
每个训练窗口默认 60 秒；至少 8 个有效片段、峰值达标率至少 80% 时，目标增加 1 度，最高 15 度。
目标升级不发送额外震动。正常脉冲到期、停止 App、关闭反馈和无效输入均使用新版停止接口。

## 检查范围

上一级 `verification/test_v19_7_recording_types.py` 检查初始、传感器缺失、预热、命令事件和训练计数状态下全部 155 个记录字段的类型，以及保存与推流一致性。
`verification/test_v19_7_viewer.py` 检查数据解析、断流提示、重连和 Tk 曲线绘制。离线检查不代表已经完成实际 Hub 和电机测试。
原来的 `min_feedback_state` / `vibration_last_duration_sec` 仍属于算法命令记录。实测通道使用下列新字段。

## 保存的实测与命令数据

- `vibration_accel_x/y/z`：该节点的原始三轴加速度；SDK 也会保存带 `_vibration_monitor` 后缀的原始数据。
- `vibration_sampletime_ms`：原始传感器时钟；`vibration_sensor_time_sec` 为展开 16 位回绕后的相对时间。
- `vibration_signal_time_sec`：以首次收包时刻对齐的传感器时间；`vibration_arrival_time_sec` 和 `vibration_queue_lag_sec` 用于检查处理滞后。这种对齐不等于经过仪器同步的精密延迟测量。
- `vibration_rms_mps2`：三轴高通加速度的短窗 RMS，默认高通 10 Hz、窗口 50 ms。
- `vibration_monitor_valid`：滤波预热/数据异常为 0；`vibration_monitor_quality`：0 预热，1 有效，2 加速度无效，3 时钟异常，4 间隙，5 未能保存完整原始包。
- `vibration_command_on/off_event`、`vibration_command_id`、`vibration_command_on/off_time_sec`、请求时长/强度及返回时刻：独立保存命令时间，不等同于设备 ACK。
- `vibration_measured_state`：-1 未知、0 低于阈值、1 振动候选。默认阈值为 0，只记录信号，不推断是否震动。
- `vibration_comparison_state`：0 未知、1 两者安静、2 候选重合、3 有命令但未检测、4 无命令但仍检测、5 起止容差窗口。所有检测结果均需实机验证。

## 采集后查看是否配对

双击 `分析震动配对.cmd`，选择本版采集的 CSV，输入通过静止开/关对照确定的 RMS 阈值。
也可运行：`python analyze_vibration_recording.py trial.csv --threshold 0.5`。0.5 只是命令示例，不是经过验证的推荐阈值。
不设置阈值或填 0 时，仍会导出每次命令，但结果标为 `UNKNOWN_THRESHOLD`。

输入文件保持只读；同目录生成 `_vibration_pairs.csv`、`_vibration_episodes.csv` 和 `_vibration_summary.json`。
逐次报告包含请求/实测起止时间、时长、起震延迟、峰值 RMS，以及候选匹配、未检测、时长不符、持续上一段、数据中断和未完整记录等结果。
一次持续震动不会被重复配给多条命令；数据中断和记录提前结束不会判为正常配对。

100 Hz 加速度不能保证捕捉所有马达频率，行走也会产生干扰。必须先确认静止时能可靠区分马达开/关，再验证行走干扰。
没有明显加速度差异不等于电机未震动；这时需要更合适的外部测量通道。软件不会宣称“物理配对已确认”。

接口参考：https://docs.sagemotion.com/app_writing/python-api
