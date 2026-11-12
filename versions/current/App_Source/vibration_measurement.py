"""Record vibration command timing and optional sensor measurement metrics.

V19.81 uses a separate feedback node, so its monitor stream is intentionally
disabled while command timing remains available.
"""
from collections import deque
import math


INT_FIELDS = (
    "vibration_measurement_schema_version", "vibration_monitor_valid",
    "vibration_monitor_quality", "vibration_detection_configured",
    "vibration_measured_state", "vibration_measured_on_event",
    "vibration_measured_off_event", "vibration_command_state",
    "vibration_command_on_event", "vibration_command_off_event",
    "vibration_command_id", "vibration_command_on_count",
    "vibration_command_off_count", "vibration_command_error_count",
    "vibration_command_strength", "vibration_expected_state",
    "vibration_comparison_state",
)
FLOAT_FIELDS = (
    "vibration_accel_x", "vibration_accel_y", "vibration_accel_z",
    "vibration_sampletime_ms", "vibration_sensor_time_sec",
    "vibration_signal_time_sec", "vibration_arrival_time_sec",
    "vibration_queue_lag_sec", "vibration_monitor_package",
    "vibration_rms_mps2", "vibration_threshold_mps2",
    "vibration_highpass_hz", "vibration_rms_window_ms",
    "vibration_measured_on_time_sec", "vibration_measured_off_time_sec",
    "vibration_command_on_time_sec", "vibration_command_off_time_sec",
    "vibration_command_expected_end_sec", "vibration_command_duration_sec",
    "vibration_command_return_time_sec", "vibration_match_tolerance_sec",
    "vibration_on_dwell_ms", "vibration_off_dwell_ms",
)


class EnvelopeDetector:
    """Threshold a measured RMS envelope, independently of command state."""
    def __init__(self, threshold=0.0, on_dwell=0.02, off_dwell=0.04):
        self.threshold = float(threshold)
        self.on_dwell = float(on_dwell)
        self.off_dwell = float(off_dwell)
        if not all(math.isfinite(x) and x >= 0 for x in
                   (self.threshold, self.on_dwell, self.off_dwell)):
            raise ValueError("Invalid vibration detector settings")
        self.reset()

    def reset(self):
        self.state = -1
        self.candidate_since = None
        self.last_time = None

    def update(self, rms, timestamp, valid=True):
        if (not valid or self.threshold <= 0 or not math.isfinite(rms)
                or not math.isfinite(timestamp)
                or (self.last_time is not None and timestamp <= self.last_time)):
            self.reset()
            return -1, None, None
        self.last_time = timestamp
        if self.state == -1:
            self.state = 0
        crossing = rms >= self.threshold if self.state == 0 else rms < self.threshold * 0.7
        if not crossing:
            self.candidate_since = None
            return self.state, None, None
        if self.candidate_since is None:
            self.candidate_since = timestamp
        dwell = self.on_dwell if self.state == 0 else self.off_dwell
        if timestamp - self.candidate_since + 1e-9 < dwell:
            return self.state, None, None
        event_time = self.candidate_since
        self.state = 1 - self.state
        self.candidate_since = None
        return self.state, "on" if self.state else "off", event_time


class VibrationMeasurement:
    def __init__(self, datarate, origin, threshold=0.0, highpass_hz=10.0,
                 window_ms=50.0, tolerance_sec=0.15):
        self.datarate = float(datarate)
        self.origin = float(origin)
        self.highpass_hz = float(highpass_hz)
        self.window_ms = float(window_ms)
        self.tolerance = float(tolerance_sec)
        if (not all(math.isfinite(x) for x in (self.datarate, self.origin,
                self.highpass_hz, self.window_ms, self.tolerance))
                or self.datarate <= 0 or not 0 < self.highpass_hz < self.datarate / 2
                or self.window_ms <= 0 or self.tolerance < 0):
            raise ValueError("Invalid vibration measurement settings")
        self.window_samples = max(2, int(math.ceil(self.window_ms * self.datarate / 1000)))
        self.energy = deque(maxlen=self.window_samples)
        self.detector = EnvelopeDetector(threshold)
        self.previous_accel = None
        self.highpass = [0.0] * 3
        self.last_tick = None
        self.sensor_elapsed = 0.0
        self.sensor_origin_wall = None
        self.recent_commands = deque(maxlen=256)
        self.values = dict.fromkeys(INT_FIELDS, 0)
        self.values.update(dict.fromkeys(FLOAT_FIELDS, 0.0))
        self.values.update(vibration_measurement_schema_version=1,
                           vibration_measured_state=-1,
                           vibration_threshold_mps2=self.detector.threshold,
                           vibration_detection_configured=int(threshold > 0),
                           vibration_highpass_hz=self.highpass_hz,
                           vibration_rms_window_ms=self.window_ms,
                           vibration_match_tolerance_sec=self.tolerance,
                           vibration_on_dwell_ms=20.0,
                           vibration_off_dwell_ms=40.0,
                           vibration_measured_on_time_sec=-1.0,
                           vibration_measured_off_time_sec=-1.0,
                           vibration_command_on_time_sec=-1.0,
                           vibration_command_off_time_sec=-1.0,
                           vibration_command_expected_end_sec=-1.0)

    def begin_frame(self):
        for name in ("vibration_measured_on_event", "vibration_measured_off_event",
                     "vibration_command_on_event", "vibration_command_off_event"):
            self.values[name] = 0

    def _invalidate(self, quality):
        self.values.update(vibration_monitor_valid=0,
                           vibration_monitor_quality=quality,
                           vibration_measured_state=-1)
        self.previous_accel = None
        self.highpass = [0.0] * 3
        self.energy.clear()
        self.detector.reset()

    def mark_recording_gap(self):
        self._invalidate(5)

    def disable_sensor_monitoring(self):
        """Record that V19.81 does not stream the separate feedback node."""
        self.values.update(vibration_monitor_valid=0,
                           vibration_monitor_quality=6,
                           vibration_measured_state=-1,
                           vibration_expected_state=int(
                               self.values["vibration_command_state"]),
                           vibration_comparison_state=0)

    def update(self, node, now):
        v = self.values
        v["vibration_arrival_time_sec"] = float(now) - self.origin
        try:
            accel = [float(node[k]) for k in ("AccelX", "AccelY", "AccelZ")]
            tick = float(node["Sampletime"])
            package = float(node.get("Package", 0))
            if not all(math.isfinite(x) for x in accel + [tick, package]):
                raise ValueError("Nonfinite monitor data")
        except (TypeError, ValueError, KeyError, AttributeError):
            self._invalidate(2)
            return
        for name, value in zip(("vibration_accel_x", "vibration_accel_y", "vibration_accel_z"), accel):
            v[name] = value
        v["vibration_sampletime_ms"] = tick
        v["vibration_monitor_package"] = package
        if not 0 <= tick < 65536:
            self._invalidate(3)
            return
        dt = 1.0 / self.datarate
        if self.last_tick is not None:
            delta = tick - self.last_tick
            if delta < 0 and self.last_tick > 60000 and tick < 5000:
                delta += 65536
            if delta <= 0:
                self._invalidate(3)
                return
            dt = delta / 1000.0
            self.sensor_elapsed += dt
        else:
            self.sensor_origin_wall = v["vibration_arrival_time_sec"]
        self.last_tick = tick
        v["vibration_sensor_time_sec"] = self.sensor_elapsed
        v["vibration_signal_time_sec"] = self.sensor_origin_wall + self.sensor_elapsed
        v["vibration_queue_lag_sec"] = max(0.0, v["vibration_arrival_time_sec"] - v["vibration_signal_time_sec"])
        if dt > 0.1:
            self._invalidate(4)
            return
        if self.previous_accel is None:
            self.previous_accel = accel
        alpha = math.exp(-2.0 * math.pi * self.highpass_hz * dt)
        self.highpass = [alpha * (h + x - old) for h, x, old in
                         zip(self.highpass, accel, self.previous_accel)]
        self.previous_accel = accel
        self.energy.append(sum(x * x for x in self.highpass))
        rms = math.sqrt(sum(self.energy) / len(self.energy))
        ready = len(self.energy) == self.window_samples
        v.update(vibration_rms_mps2=rms, vibration_monitor_valid=int(ready),
                 vibration_monitor_quality=1 if ready else 0)
        state, event, timestamp = self.detector.update(rms, v["vibration_signal_time_sec"], ready)
        v["vibration_measured_state"] = state
        if event:
            v["vibration_measured_" + event + "_event"] = 1
            v["vibration_measured_" + event + "_time_sec"] = timestamp

    def command_on(self, now, returned, duration, strength):
        v = self.values
        start = float(now) - self.origin
        end = start + float(duration)
        v["vibration_command_id"] += 1
        v["vibration_command_on_count"] += 1
        v.update(vibration_command_state=1, vibration_command_on_event=1,
                 vibration_command_on_time_sec=start,
                 vibration_command_expected_end_sec=end,
                 vibration_command_duration_sec=float(duration),
                 vibration_command_strength=int(strength),
                 vibration_command_return_time_sec=float(returned) - self.origin)
        self.recent_commands.append([start, end])

    def command_off(self, now, returned):
        v = self.values
        stop = float(now) - self.origin
        if v["vibration_command_state"] and self.recent_commands:
            self.recent_commands[-1][1] = min(self.recent_commands[-1][1], stop)
            v["vibration_command_expected_end_sec"] = self.recent_commands[-1][1]
        v["vibration_command_off_count"] += 1
        v.update(vibration_command_state=0, vibration_command_off_event=1,
                 vibration_command_off_time_sec=stop,
                 vibration_command_return_time_sec=float(returned) - self.origin)

    def command_error(self):
        self.values["vibration_command_error_count"] += 1

    def metrics(self):
        v = self.values
        if not v["vibration_monitor_valid"]:
            v["vibration_expected_state"] = int(v["vibration_command_state"])
            v["vibration_comparison_state"] = 0
            return dict(v)
        stamp = v["vibration_signal_time_sec"]
        windows = [w for w in self.recent_commands if w[0] <= stamp]
        expected = int(any(start <= stamp < end for start, end in windows))
        v["vibration_expected_state"] = expected
        detected = v["vibration_measured_state"]
        if not v["vibration_monitor_valid"] or detected < 0:
            comparison = 0
        elif expected and detected:
            comparison = 2
        elif not expected and not detected:
            comparison = 1
        elif any(abs(stamp - edge) <= self.tolerance for w in self.recent_commands for edge in w):
            comparison = 5
        else:
            comparison = 3 if expected else 4
        v["vibration_comparison_state"] = comparison
        return dict(v)
