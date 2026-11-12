# V19.81 release notes

Compared with the previous V19.8 package, V19.81 changes the feedback-node configuration and command API. The hip-extension training loop remains in place.

## 中文

### App 版本

- App 版本从 `1_19_8vibrant` 更新为 `1_19_81vibrant`。
- build 从 `901800` 更新为 `901810`。

### 传感器与 feedback 节点

| 项目 | V19.8 | V19.81 |
|---|---|---|
| `sensors` | `right_thigh`、`left_thigh`、`pelvis`、`vibration_monitor` | `right_thigh`、`left_thigh`、`pelvis` |
| `feedback` | 空 | `feedback_min` |

V19.81 不再把震动节点作为第四颗传感器读取。Hub 中应把三颗姿态 IMU 放在 **sensors**，把 `feedback_min` 单独放在 **feedback**；不要把同一颗实体节点同时放入两个列表。

### 震动命令接口

- V19.8 使用 `sensor_vibration_on()` / `sensor_vibration_off()`。
- V19.81 改用 `feedback_vibration_on()` / `feedback_vibration_off()`。
- `feedback_min` 负责接收震动启停命令；髋角计算和闭环判断仍由 Hub App 执行。
- Hub SDK 必须支持新的 `feedback_vibration_on/off` API。

### 记录与实测范围

- App 保留震动命令状态、on/off 事件、请求时间、请求时长、强度及错误计数。
- 这些字段记录的是 App 发出的命令，不是电机实际振动的确认。
- 因为 feedback 节点不再作为 sensor 数据流读取，V19.81 不提供该节点的加速度、RMS 或命令与实测振动配对结果。
- 为兼容记录结构，振动测量字段保留为无效占位；`vibration_monitor_valid=0`，`vibration_monitor_quality=6)。

### 保持不变的训练逻辑

- 髋后伸角度计算、目标达成判断、每个合格后伸周期的奖励震动，以及周期重新触发门控均沿用 V19.8。
- 自动评估和训练目标自适应更新逻辑沿用 V19.8。
- 默认奖励震动仍为 **0.2 秒、强度 2**；软件请求时长上限仍为 **0.25 秒**。

### 查看器

- 发布了适配 V19.81 的 Windows 查看器，订阅 27 项 App 指标。
- 查看器显示髋角、训练目标、震动命令事件及静态站立校准状态、稳定计时、偏差和重置次数。
- 查看器只通过 Hub WebSocket 接收数据和状态，不连接 IMU 或 feedback 节点，也不发送震动命令。

### 发布与验证说明

- 当前发布内容放在稳定路径 `versions/current/`，没有新建 `v19.81` 版本目录；之前的 V19.8 文件仍可从 Git 历史查看。
- SHA256 清单随发布包更新。
- 本次没有执行 V19.81 离线测试或实机验证。

## English

V19.81 updates the feedback-node assignment and vibration API. The hip-extension closed-loop training behavior is retained.

- App version: `1_19_8vibrant` → `1_19_81vibrant`; build: `901800` → `901810`.
- Sensors: remove `vibration_monitor`; keep `right_thigh`, `left_thigh`, and `pelvis`.
- Feedback: assign `feedback_min` to the separate `feedback` list.
- Vibration API: replace `sensor_vibration_on/off()` with `feedback_vibration_on/off()`.
- The feedback node receives on/off commands only. Its accelerometer is no longer streamed; vibration acceleration, RMS, and command-to-measurement pairing are unavailable. Command fields remain request records, not proof of physical motor response. Measurement fields are invalid placeholders (`vibration_monitor_valid=0`, quality `6`).
- Hip-angle calculation, closed-loop reward conditions, per-cycle re-trigger gating, and adaptive target updates are retained. Default reward remains 0.2 seconds at strength 2, with a 0.25-second software cap.
- The Windows viewer is adapted to 27 App metrics and displays angle, target, command events, and standing-calibration status. It is WebSocket read-only and does not contact the IMUs or feedback node.
- The active package now lives in `versions/current/`; the previous V19.8 files remain in Git history. No V19.81 offline tests or hardware validation were run for this publication.
