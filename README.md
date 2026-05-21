# IMU Hip Extension Feedback

Phase 1 app for real-time hip extension feedback using SageMotion IMU/Dot nodes.

This package is based on the official Hip Extension app and adds:

- Angle-threshold feedback
- 5-sample moving average smoothing
- Hysteresis to prevent vibration chatter
- Feedback cooldown
- Optional movement gate using thigh gyroscope magnitude
- Diagnostic save fields for offline validation
- Optional v1.4 orientation debug output:
  - terminal/log print of each IMU yaw/pitch/roll and X/Y/Z axes
  - UDP JSON stream for a desktop Python 3D orientation viewer
  - v1.4.1 UDP send/error counters saved with trial data

### Nodes Required: 4
- **Sensing (3)**:
  - pelvis (back center, switch pointing up)
  - right_thigh (right lateral thigh, switch pointing up)
  - left_thigh (left lateral thigh, switch pointing up)
- **Feedback (1)**:
  - feedback_min

### Feedback Timing

Feedback is only allowed when:

1. the right thigh is in the configured back-leg phase, and
2. the left thigh is in the configured forward phase, and
3. the right hip is entering extension.

Inside that target phase, the app vibrates `feedback_min` only when the right hip extension metric crosses the feedback threshold. Once terminal range is reached, the app stops vibration until the next flexion/reset cycle.

Slow movements are handled by a trend window:

- `right_hip_velocity`: frame-to-frame right hip angle change
- `right_hip_trend`: right hip angle change over the configured trend window

### Orientation Debug Viewer

v1.4 emits each IMU orientation over UDP at a low debug rate by default without
changing the feedback state machine. Terminal printing is off by default because
plain text output can confuse the SageMotion browser plot websocket.

Recommended debug settings:

```json
{
  "debug_orientation_enabled": true,
  "debug_orientation_print_enabled": false,
  "debug_orientation_udp_enabled": true,
  "debug_orientation_hz": 5,
  "debug_orientation_udp_host": "192.168.12.255",
  "debug_orientation_udp_port": 50514
}
```

Start the desktop viewer on the computer connected to the SageMotion Wi-Fi:

```bash
python3 scripts/realtime_imu_orientation_viewer.py --port 50514
```

For offline replay tests, add an idle timeout so the viewer closes after the
data stream ends:

```bash
python3 scripts/realtime_imu_orientation_viewer.py --host 127.0.0.1 --port 50514 --idle-timeout 3
```

The viewer expects `matplotlib` to be available in the desktop Python
environment.

UDP diagnostics are saved and streamed with each sample:

- `debug_orientation_enabled_state`: 1 when orientation debug is enabled
- `debug_orientation_udp_enabled_state`: 1 when UDP output is enabled
- `debug_orientation_udp_send_count`: number of successful UDP packets sent
- `debug_orientation_udp_error_count`: number of UDP send errors
- `debug_orientation_udp_last_error_code`: last socket error number, or 0 after success
- `debug_orientation_udp_target_port`: UDP destination port
- `debug_orientation_udp_target_last_octet`: last IPv4 octet of the configured UDP host

---

## Algorithm & Calibration

### Algorithm Information
The app uses quaternion data from IMUs to calculate 3D joint angles. The orientation is converted into XYZ Euler angles, from which the sagittal plane (hip extension) angle is extracted. This angle reflects relative rotation between the thigh and pelvis segments.

### Calibration Process
On the first iteration, the app aligns sensor orientation to body segment alignment:
- Calculates yaw offset between pelvis and thigh
- Applies this alignment to correct global measurements
- Uses predefined target orientation as a reference

---

## Description of Data in Downloaded File

### Calculated Fields
- **time (sec)**: time since trial start
- **Hip_ext (deg)**: hip flexion/extension angle
- **filtered_Hip_ext (deg)**: smoothed hip angle used by the default feedback mode
- **right_Hip_ext / left_Hip_ext**: raw right and left hip angle estimates
- **filtered_right_Hip_ext / filtered_left_Hip_ext**: smoothed bilateral hip angles
- **min_feedback_state**: single vibration feedback state
- **right_leg_back_state / left_leg_forward_state / target_phase_state**: bilateral phase gate states
- **right_hip_velocity / right_hip_trend**: instantaneous and slow-trend motion signals
- **right_hip_extending_state / right_hip_flexing_state**: motion direction states
- **feedback_phase_state**: 0 waiting, 1 extending, 2 terminal range reached
- **feedback_mode_code**: 0 angle, 1 gyro magnitude, 2 acceleration magnitude
- **feedback_reason_code**: 0 terminal range reached, 1 insufficient hip extension, 3 phase gate blocked, 4 waiting for extension, 5 qualified, 6 flexion reset
- **gyro_mag / acc_mag**: thigh movement features used for diagnostics and optional feedback modes

### Sensor Raw Data Fields (repeated for each sensor)
- SensorIndex
- AccelX/Y/Z (m/s²)
- GyroX/Y/Z (deg/s)
- MagX/Y/Z (μT)
- Quat1/2/3/4 (quaternion, scalar first order)
- Sampletime (timestamp)
- Package (packet number)


## Development Notes
The best place to start when developing a new app or modifying an existing one is the [SageMotion Documentation](http://docs.sagemotion.com/index.html) page.
