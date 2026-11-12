#!/usr/bin/env python3
import argparse
import json
import math
import queue
import threading
import time
import urllib.request
from collections import deque


VIEWER_VERSION = "19.81"
VIEWER_BUILD = "901810"

HUB_DEFAULT_IP = "192.168.137.1"
DEFAULT_WS_PORT = 5678
DEFAULT_HISTORY_SEC = 60.0
DEFAULT_STALE_AFTER_SEC = 2.0
QUAT_FIELDS = ("Quat1", "Quat2", "Quat3", "Quat4")
METRIC_FIELDS = (
    "time",
    "hip_calibrated_state",
    "standing_calibration_state",
    "standing_stable_elapsed_sec",
    "standing_stability_reset_count",
    "standing_stability_deviation_deg",
    "data_valid_state",
    "filtered_selected_Hip_ext",
    "selected_hip_signed_extension_deg",
    "feedback_reason_code",
    "feedback_interval_ms",
    "adaptive_current_threshold",
    "adaptive_mode_state",
    "adaptive_assessed_threshold",
    "adaptive_assessment_elapsed_sec",
    "adaptive_assessment_extension_sample_count",
    "adaptive_current_level",
    "adaptive_level_up_event_state",
    "adaptive_current_step_peak_deg",
    "adaptive_last_step_peak_deg",
    "adaptive_last_step_success_state",
    "vibration_total_count",
    "vibration_last_duration_sec",
    "vibration_last_strength",
    "angle_feedback_level",
    "deficit_feedback_deficit_deg",
    "deficit_feedback_success_latched_state",
)
REQUESTED_DATA = None


class LatestValueQueue(queue.Queue):
    def __init__(self):
        super().__init__(maxsize=1)

    def put(self, item, block=True, timeout=None):
        while True:
            try:
                self.get_nowait()
            except queue.Empty:
                break
        return super().put(item, block=False)


def drain_latest(data_queue):
    latest = None
    while True:
        try:
            latest = data_queue.get_nowait()
        except queue.Empty:
            return latest


def clean_float(value, digits=6):
    rounded = round(float(value), digits)
    return 0.0 if abs(rounded) < 10 ** -digits else rounded


def unwrap_value(value):
    if isinstance(value, (list, tuple)) and len(value) == 1:
        return value[0]
    return value


def decode_ws_message(message):
    if isinstance(message, bytes):
        message = message.decode("utf-8")
    if isinstance(message, str):
        return json.loads(message)
    return message


def normalize_message_container(message):
    if not isinstance(message, dict):
        return message
    for key in ("data", "payload", "message", "values"):
        nested = message.get(key)
        if isinstance(nested, (dict, list)):
            return nested
    return message


def metric_float(metrics, field_name, default=None):
    value = metrics.get(field_name, default)
    if value is None:
        return default
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def metric_int(metrics, field_name, default=0):
    value = metric_float(metrics, field_name, default)
    if value is None:
        return default
    return int(value)


def training_angle(metrics):
    if metric_int(metrics, "data_valid_state", 1) == 0:
        return None
    return metric_float(
        metrics,
        "filtered_selected_Hip_ext",
        metric_float(metrics, "selected_Hip_ext", None),
    )


def training_extension_metric(metrics):
    if metric_int(metrics, "data_valid_state", 1) == 0:
        return None
    signed_extension = metric_float(metrics, "selected_hip_signed_extension_deg", None)
    if signed_extension is not None:
        return signed_extension
    angle = training_angle(metrics)
    if angle is None:
        return None
    return -float(angle)


def movement_direction_label(metrics):
    if metric_int(metrics, "selected_hip_forward_side_state", 0):
        return "FORWARD"
    if metric_int(metrics, "selected_hip_extension_side_state", 0):
        return "EXTENSION"
    extension = training_extension_metric(metrics)
    if extension is None:
        return "--"
    if extension < 0:
        return "FORWARD"
    if extension > 0:
        return "EXTENSION"
    return "NEUTRAL"


def current_threshold(metrics):
    return metric_float(
        metrics,
        "adaptive_current_threshold",
        metric_float(metrics, "min_threshold", None),
    )


def app_schema_is_current(metrics):
    required_fields = (
        "filtered_selected_Hip_ext",
        "selected_hip_signed_extension_deg",
        "adaptive_current_threshold",
        "adaptive_mode_state",
        "adaptive_assessed_threshold",
        "adaptive_assessment_elapsed_sec",
        "data_valid_state",
        "hip_calibrated_state",
        "standing_calibration_state",
        "standing_stability_deviation_deg",
        "standing_stability_reset_count",
    )
    return all(metrics.get(field_name) is not None for field_name in required_fields)


def app_schema_uses_step_peaks(metrics):
    return (
        metrics.get("adaptive_current_step_peak_deg") is not None
        and metrics.get("adaptive_last_step_peak_deg") is not None
    )


def standing_calibration_state_label(state):
    return {
        0: "等待稳定站姿",
        1: "稳定采样中",
        2: "检测到移动，重新计时",
        3: "站立校准完成",
        4: "数据中断，重新采样",
    }.get(metric_int({"state": state}, "state", -1), "未知")


def standing_calibration_summary(metrics):
    state = metric_int(metrics, "standing_calibration_state", -1)
    elapsed = metric_float(metrics, "standing_stable_elapsed_sec", None)
    deviation = metric_float(metrics, "standing_stability_deviation_deg", None)
    resets = metric_int(metrics, "standing_stability_reset_count", 0)
    elapsed_text = "--" if elapsed is None else "{:.2f}s".format(elapsed)
    deviation_text = "--" if deviation is None else "{:.2f}°".format(deviation)
    return "静态站立：{} | 稳定时间 {} / 2.00s | 最大姿态偏差 {} | 重置次数 {}".format(
        standing_calibration_state_label(state), elapsed_text, deviation_text, resets
    )


def current_training_level(metrics):
    return max(1, metric_int(metrics, "adaptive_current_level", 1))


def adaptive_mode_label(metrics):
    return {
        0: "DISABLED",
        1: "ASSESSMENT",
        2: "TRAINING",
    }.get(metric_int(metrics, "adaptive_mode_state", 2), "TRAINING")


def adaptive_ratio_percent(metrics):
    percent = metric_float(metrics, "adaptive_success_ratio_percent", None)
    if percent is not None:
        return percent
    ratio = metric_float(metrics, "adaptive_success_ratio", None)
    if ratio is None:
        return None
    return ratio * 100.0


def adaptive_status_summary(metrics):
    if not app_schema_is_current(metrics):
        return "V19.81 指标未就绪"
    mode = adaptive_mode_label(metrics)
    assessed = metric_float(metrics, "adaptive_assessed_threshold", None)
    elapsed = metric_float(metrics, "adaptive_assessment_elapsed_sec", None)
    samples = metric_int(metrics, "adaptive_assessment_extension_sample_count", 0)
    current_peak = metric_float(metrics, "adaptive_current_step_peak_deg", None)
    last_peak = metric_float(metrics, "adaptive_last_step_peak_deg", None)
    last_success = metric_int(metrics, "adaptive_last_step_success_state", 0)
    assessed_text = "--" if assessed is None else "{:.1f} deg".format(assessed)
    elapsed_text = "--" if elapsed is None else "{:.1f}s".format(elapsed)
    current_text = "--" if current_peak is None else "{:.1f} deg".format(current_peak)
    last_text = "--" if last_peak is None else "{:.1f} deg".format(last_peak)
    last_label = "PASS" if last_success else "MISS"
    return "{} | assessed {} | assessment {} | samples {} | current peak {} | last peak {} {}".format(
        mode, assessed_text, elapsed_text, samples, current_text, last_text, last_label
    )

def feedback_status_summary(metrics):
    duration = metric_float(metrics, "vibration_last_duration_sec", None)
    strength = metric_int(metrics, "vibration_last_strength", 0)
    interval = metric_float(metrics, "feedback_interval_ms", None)
    total = metric_int(metrics, "vibration_total_count", 0)
    duration_text = "--" if duration is None else "{:.2f}s".format(duration)
    interval_text = "--" if interval is None else "{:.0f}ms".format(interval)
    return "last command {} | strength {} | interval {} | total command pulses {}".format(
        duration_text, strength, interval_text, total
    )

def header_summary(metrics):
    if not metrics:
        return "Waiting for hip angle and target data"
    if not app_schema_is_current(metrics):
        extension = training_extension_metric(metrics)
        threshold = current_threshold(metrics)
        extension_text = "--" if extension is None else "{:.1f}".format(extension)
        threshold_text = "--" if threshold is None else "{:.1f}".format(threshold)
        return (
            "APP/VERSION MISMATCH | Current extension {} deg | Target {}"
        ).format(extension_text, threshold_text)

    extension = training_extension_metric(metrics)
    threshold = current_threshold(metrics)
    deficit = metric_float(metrics, "deficit_feedback_deficit_deg", None)
    level = metric_int(metrics, "angle_feedback_level", 0)
    latched = metric_int(metrics, "deficit_feedback_success_latched_state", 0)
    direction = movement_direction_label(metrics)
    mode = adaptive_mode_label(metrics)
    level_up = metric_int(metrics, "adaptive_level_up_event_state", 0)
    current_step_peak = metric_float(metrics, "adaptive_current_step_peak_deg", None)
    last_step_peak = metric_float(metrics, "adaptive_last_step_peak_deg", None)
    last_step_success = metric_int(metrics, "adaptive_last_step_success_state", 0)
    extension_text = "--" if extension is None else "{:.1f}".format(extension)
    threshold_text = "--" if threshold is None else "{:.1f}".format(threshold)
    deficit_text = "--" if deficit is None else "{:.1f}".format(deficit)
    current_peak_text = (
        "--" if current_step_peak is None else "{:.1f}".format(current_step_peak)
    )
    last_peak_text = "--" if last_step_peak is None else "{:.1f}".format(last_step_peak)
    last_peak_label = "PASS" if last_step_success else "MISS"
    prefix = "ASSESSMENT" if mode == "ASSESSMENT" else "TRAINING LEVEL {}".format(
        current_training_level(metrics)
    )
    if level_up:
        prefix = "{} | LEVEL UP".format(prefix)
    return (
        "{} | {} | Current extension {} deg | "
        "Step peak {} deg | Last peak {} {} | "
        "Target {} | Deficit {} | {} | latch {}"
    ).format(
        prefix,
        direction,
        extension_text,
        current_peak_text,
        last_peak_text,
        last_peak_label,
        threshold_text,
        deficit_text,
        level_label(level),
        latched,
    )


def build_requested_data():
    requested = []
    for field_name in METRIC_FIELDS:
        requested.append([None, field_name])
    return requested


REQUESTED_DATA = build_requested_data()


def numeric_values(values):
    result = []
    for value in values:
        if value is None:
            continue
        try:
            converted = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(converted):
            result.append(converted)
    return result


def plot_value_range(history, padding_ratio=0.12, min_span=10.0):
    values = numeric_values(history.extensions) + numeric_values(history.thresholds)
    if not values:
        return 0.0, 15.0
    low = min(values)
    high = max(values)
    span = max(float(min_span), high - low)
    padding = span * float(padding_ratio)
    return low - padding, high + padding


class ConnectionStatus:
    def __init__(self, stale_after_sec=DEFAULT_STALE_AFTER_SEC):
        self.stale_after_sec = float(stale_after_sec)
        self.last_packet_wall_time = None
        self.packet_count = 0
        self.connected = False
        self.error = ""
        self.data_error = ""
        self.app_state = ""
        self.app_name = ""
        self.app_version_id = ""
        self.hub_error = ""

    def apply_event(self, event):
        kind, value = event
        if kind == "connected":
            self.connected = True
            self.error = ""
        elif kind in ("error", "closed"):
            self.connected = False
            # A close callback must not hide the preceding connection error.
            if kind == "error" or not self.error:
                self.error = str(value)
        elif kind == "hub":
            self.app_state = str(value.get("app_state", "UNKNOWN"))
            self.app_name = str(value.get("current_app", ""))
            self.app_version_id = str(value.get("app_version_id", ""))
            self.hub_error = ""
        elif kind == "hub_error":
            self.hub_error = str(value)

    def mark_packet(self, now=None):
        self.last_packet_wall_time = time.monotonic() if now is None else float(now)
        self.packet_count += 1
        self.data_error = ""

    def is_stale(self, now=None):
        if self.last_packet_wall_time is None:
            return True
        current = time.monotonic() if now is None else float(now)
        return current - self.last_packet_wall_time > self.stale_after_sec

    def label(self, now=None):
        if self.error:
            return "Connection error: {}".format(self.error)
        if self.data_error:
            return "Data error: {}".format(self.data_error)
        if self.last_packet_wall_time is None:
            state = "connected" if self.connected else "connecting"
            return "{}; waiting for samples; App {}".format(state, self.app_state or "unknown")
        current = time.monotonic() if now is None else float(now)
        age = max(0.0, current - self.last_packet_wall_time)
        if age > self.stale_after_sec:
            return "stale: last packet {:.1f}s ago".format(age)
        return "live: {} packets, last {:.1f}s ago".format(self.packet_count, age)


def viewer_prompt(status, metrics):
    if status.error or status.data_error:
        return status.label(), "#b00020"
    if status.app_state == "CONFIGURE" and not status.hub_error:
        return "Hub 已连接，App 尚在配置状态。请完成配置并在 Hub 页面点击 Start。", "#9a6700"
    if status.app_state in ("READY", "READY TO RUN", "FINISHED", "STOPPED") and not status.hub_error:
        return "Hub 已连接，App 尚未运行。请在 Hub 页面启动 V19.81 App。", "#9a6700"
    if not metrics or status.is_stale():
        if status.connected:
            if status.app_state == "RUNNING" and not status.hub_error:
                if status.packet_count:
                    return "实时数据已中断或过期；请检查 Hub 与传感器连接。", "#b00020"
                return "App 正在运行，等待有效髋角度数据。", "#9a6700"
            return "数据通道已连接，等待 App 开始发送数据。", "#9a6700"
        return "正在连接 Hub；请检查网络、Hub 电源和 IP 地址。", "#9a6700"
    if not app_schema_is_current(metrics):
        return "当前 App 指标与 V19.81 查看器不匹配；请确认 Hub 正在运行 build 901810。", "#b00020"
    if metric_int(metrics, "data_valid_state", 1) == 0:
        return "已收到数据，但姿态帧无效。请检查三颗姿态 IMU 的连接。", "#b00020"
    if metric_int(metrics, "hip_calibrated_state", 1) == 0:
        standing_state = metric_int(metrics, "standing_calibration_state", 0)
        elapsed = metric_float(metrics, "standing_stable_elapsed_sec", 0.0)
        deviation = metric_float(metrics, "standing_stability_deviation_deg", 0.0)
        prompt = "静态站立：{} | 稳定 {:.2f}/2.00s | 最大姿态偏差 {:.2f}°。".format(
            standing_calibration_state_label(standing_state), elapsed, deviation
        )
        return prompt + "请自然站立保持稳定。", "#9a6700"
    if metric_int(metrics, "adaptive_mode_state", 0) == 1:
        return "站立校准完成，正在进行能力评估；请自然行走。", "#16713b"
    return "实时数据已连接；蓝线为髋后伸角度，绿线为当前目标，红点为震动命令。", "#16713b"

def build_payload_from_ws_message(message, sample_index):
    raw = normalize_message_container(decode_ws_message(message))
    metrics = {}
    if isinstance(raw, dict):
        custom_data = raw.get("custom_data")
        if isinstance(custom_data, dict):
            for key, value in custom_data.items():
                metrics[str(key)] = unwrap_value(value)
        for field_name in METRIC_FIELDS:
            if field_name in raw:
                metrics[field_name] = unwrap_value(raw[field_name])
    time_sec = metric_float(metrics, "time", None)
    if time_sec is None:
        stamp = metric_float(raw, "time_stamp_in_milliseconds", None) if isinstance(raw, dict) else None
        time_sec = stamp / 1000.0 if stamp is not None else float(sample_index) / 100.0
    return {
        "sample": int(sample_index),
        "time_sec": float(time_sec),
        "metrics": metrics,
    }


def level_label(value):
    return {
        0: "WAIT",
        1: "LEVEL 1",
        2: "LEVEL 2",
        3: "LEVEL 3",
    }.get(metric_int({"value": value}, "value", 0), "--")


def reason_label(value):
    return {
        40: "disabled/forward",
        41: "disarmed at target",
        42: "waiting reset",
        43: "level 1",
        44: "level 2",
        45: "buffer",
        46: "success dwell",
        47: "success pulse",
        48: "success latched",
    }.get(metric_int({"value": value}, "value", -1), "--")


class TrainingHistory:
    def __init__(self, history_sec=DEFAULT_HISTORY_SEC):
        self.history_sec = float(history_sec)
        self.times = deque()
        self.extensions = deque()
        self.thresholds = deque()
        self.vibration_times = deque()
        self.vibration_extensions = deque()
        self._last_vibration_total_count = None

    def append(self, time_sec, metrics):
        if self.times and float(time_sec) < self.times[-1]:
            # App restarts reset its clock; do not join two different trials.
            for values in (self.times, self.extensions, self.thresholds,
                           self.vibration_times, self.vibration_extensions):
                values.clear()
            self._last_vibration_total_count = None
        extension = training_extension_metric(metrics)
        threshold = current_threshold(metrics)
        self._append_vibration_events(float(time_sec), extension, metrics)
        self.times.append(float(time_sec))
        self.extensions.append(extension)
        self.thresholds.append(threshold)
        self._trim()

    def _append_vibration_events(self, time_sec, extension, metrics):
        total_count = metric_int(metrics, "vibration_total_count", None)
        if total_count is None:
            return
        if self._last_vibration_total_count is None:
            self._last_vibration_total_count = total_count
            return
        delta = max(0, total_count - self._last_vibration_total_count)
        self._last_vibration_total_count = total_count
        if delta <= 0:
            return
        for _index in range(delta):
            self.vibration_times.append(float(time_sec))
            self.vibration_extensions.append(extension)

    def _trim(self):
        if not self.times:
            return
        min_time = self.times[-1] - self.history_sec
        while self.times and self.times[0] < min_time:
            self.times.popleft()
            self.extensions.popleft()
            self.thresholds.popleft()
        while self.vibration_times and self.vibration_times[0] < min_time:
            self.vibration_times.popleft()
            self.vibration_extensions.popleft()


class FastTrainingCanvas:
    def __init__(self, root, history, connection_status=None):
        import tkinter as tk

        self.tk = tk
        self.root = root
        self.history = history
        self.connection_status = connection_status or ConnectionStatus()
        self.metrics = {}
        self.status_var = tk.StringVar(value="Waiting for data")
        self.prompt_var = tk.StringVar(value="正在连接 Hub")
        self.prompt = tk.Label(root, textvariable=self.prompt_var, anchor="w",
                               justify="left", font=("Microsoft YaHei UI", 12, "bold"),
                               padx=16, pady=8)
        self.prompt.pack(fill=tk.X)
        self.canvas = tk.Canvas(root, width=1160, height=500, bg="white")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.status = tk.Label(root, textvariable=self.status_var, anchor="w", justify="left")
        self.status.pack(fill=tk.X)

    def update_metrics(self, metrics):
        self.metrics = metrics

    def draw(self):
        self.canvas.delete("all")
        width = max(320, self.canvas.winfo_width())
        height = max(240, self.canvas.winfo_height())
        metrics = self.metrics
        extension = training_extension_metric(metrics)
        threshold = current_threshold(metrics)
        deficit = metric_float(metrics, "deficit_feedback_deficit_deg", None)
        level = metric_int(metrics, "angle_feedback_level", 0)
        reason = metric_int(metrics, "feedback_reason_code", -1)
        prompt, color = viewer_prompt(self.connection_status, metrics)
        self.prompt_var.set(prompt)
        self.prompt.configure(fg=color, wraplength=width - 32)
        self.status.configure(wraplength=width - 16)

        self._draw_bar(width, height, extension, threshold)
        self._draw_history(width, height)
        self.canvas.create_text(
            20,
            20,
            anchor="nw",
            text=header_summary(metrics),
            font=("Segoe UI", 12, "bold"),
        )
        self.canvas.create_text(
            20,
            48,
            anchor="nw",
            text=adaptive_status_summary(metrics) if metrics else "",
            fill="#b00020" if current_training_level(metrics) > 1 else "#444",
            font=("Segoe UI", 10, "bold"),
        )
        self.status_var.set(
            "Viewer v{} | Hub App {} | {}   reason: {}   hip extension: {} deg   feedback: {}   {}   {}".format(
                VIEWER_VERSION,
                self.connection_status.app_version_id or "--",
                self.connection_status.label(),
                reason_label(reason),
                self._fmt(training_angle(metrics)),
                level_label(level),
                feedback_status_summary(metrics),
                standing_calibration_summary(metrics),
            )
        )

    def _draw_bar(self, width, _height, extension, threshold):
        left, top, right, bottom = 40, 80, width - 40, 135
        self.canvas.create_rectangle(left, top, right, bottom, outline="#222")
        for value, color, label in ((5, "#f6c445", "5"), (10, "#4aa3df", "10"), (15, "#49a65e", "15")):
            x = left + (right - left) * value / 15.0
            self.canvas.create_line(x, top, x, bottom, fill=color, width=2)
            self.canvas.create_text(x, bottom + 16, text=label, fill=color)
        if extension is not None:
            x = left + (right - left) * max(0.0, min(15.0, extension)) / 15.0
            self.canvas.create_rectangle(left, top, x, bottom, fill="#88c0ff", outline="")
        if threshold is not None:
            x = left + (right - left) * max(0.0, min(15.0, threshold)) / 15.0
            self.canvas.create_line(x, top - 12, x, bottom + 12, fill="#111", width=3)

    def _draw_history(self, width, height):
        if len(self.history.times) < 2:
            return
        left, top, right, bottom = 40, 175, width - 40, height - 30
        self.canvas.create_rectangle(left, top, right, bottom, outline="#ddd")
        times = list(self.history.times)
        extensions = list(self.history.extensions)
        thresholds = list(self.history.thresholds)
        t0, t1 = times[0], times[-1]
        span = max(0.001, t1 - t0)
        value_low, value_high = plot_value_range(self.history)
        value_span = max(0.001, value_high - value_low)

        def point(index, value):
            x = left + (right - left) * (times[index] - t0) / span
            y = bottom - (bottom - top) * (float(value) - value_low) / value_span
            return x, y

        for marker in (0, 5, 10, 15):
            if value_low <= marker <= value_high:
                y = bottom - (bottom - top) * (float(marker) - value_low) / value_span
                self.canvas.create_line(left, y, right, y, fill="#eeeeee")
                self.canvas.create_text(left - 6, y, text=str(marker), anchor="e", fill="#777")
        self._draw_polyline(extensions, point, "#1f77b4", width=2)
        self._draw_polyline(thresholds, point, "#2ca02c", width=2)
        self._draw_vibration_events(left, right, bottom, top, t0, span, value_low, value_span)

    def _draw_polyline(self, values, point_func, color, width=1):
        coords = []
        for index, value in enumerate(values):
            if value is None:
                if len(coords) >= 4:
                    self.canvas.create_line(*coords, fill=color, width=width)
                coords = []
                continue
            coords.extend(point_func(index, value))
        if len(coords) >= 4:
            self.canvas.create_line(*coords, fill=color, width=width)

    def _draw_vibration_events(
        self,
        left,
        right,
        bottom,
        top,
        t0,
        time_span,
        value_low,
        value_span,
    ):
        radius = 4
        for event_time, event_extension in zip(
            self.history.vibration_times,
            self.history.vibration_extensions,
        ):
            if event_extension is None:
                continue
            x = left + (right - left) * (float(event_time) - t0) / time_span
            y = bottom - (bottom - top) * (float(event_extension) - value_low) / value_span
            self.canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                outline="#b00020",
                fill="#ff4d4d",
                width=2,
            )

    def _fmt(self, value):
        if value is None:
            return "--"
        return "{:.2f}".format(float(value))


class SageMotionWebSocketClient:
    def __init__(self, hub_ip, port, requested_data, data_queue, events_queue=None, stop_event=None):
        self.hub_ip = hub_ip
        self.port = int(port)
        self.requested_data = requested_data
        self.data_queue = data_queue
        self.ws_url = "ws://{}:{}/".format(hub_ip, port)
        self.events_queue = events_queue if events_queue is not None else queue.Queue()
        self.stop_event = stop_event if stop_event is not None else threading.Event()
        self.app = None
        self.last_message_time = None
        self.last_error = ""

    def on_open(self, ws):
        ws.send(json.dumps(self.requested_data))
        self.last_error = ""
        self.events_queue.put(("connected", self.ws_url))

    def on_message(self, _ws, message):
        if message in ("KEEPALIVE", b"KEEPALIVE", "", b""):
            return
        self.last_message_time = time.monotonic()
        self.data_queue.put(message)

    def on_error(self, _ws, error):
        self.last_error = str(error)
        self.events_queue.put(("error", self.last_error))

    def on_close(self, _ws, close_status_code, close_msg):
        if not self.stop_event.is_set():
            message = self.last_error or "WebSocket closed: {} {}".format(close_status_code, close_msg or "")
            self.events_queue.put(("closed", message))

    def subscribe(self):
        app = self.app
        if app is not None and app.sock is not None and app.sock.connected:
            try:
                app.send(json.dumps(self.requested_data))
            except Exception as exc:
                self.on_error(app, exc)
                app.close()

    def close(self):
        self.stop_event.set()
        if self.app is not None:
            self.app.close()

    def run_forever(self):
        try:
            import websocket
        except ImportError:
            self.events_queue.put(("error", "Missing websocket-client; install it in the Python environment running this viewer."))
            return
        websocket.setdefaulttimeout(4)
        while not self.stop_event.is_set():
            self.app = websocket.WebSocketApp(
                self.ws_url,
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close,
            )
            try:
                # Hub traffic stays on the local network, even with a system proxy.
                self.app.run_forever(http_no_proxy=[self.hub_ip], ping_interval=10, ping_timeout=5)
            except Exception as exc:
                self.on_error(self.app, exc)
            if self.stop_event.wait(2):
                break


def monitor_hub_status(hub_ip, events_queue, stop_event, client, api_port=80):
    """Read Hub state and renew subscriptions after an App restart."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = "http://{}:{}/api/v1/system_status".format(hub_ip, api_port)
    previous_app = None
    last_subscription = 0.0
    while not stop_event.is_set():
        try:
            with opener.open(url, timeout=2) as response:
                packet = json.load(response)
            status = packet["sage_status"]
            if not isinstance(status, dict):
                raise ValueError("Invalid Hub status response")
            events_queue.put(("hub", status))
            app = (status.get("app_version_id"), status.get("app_state"))
            now = time.monotonic()
            stale = client.last_message_time is None or now - client.last_message_time > 2
            if app != previous_app or (app[1] == "RUNNING" and stale and now - last_subscription >= 5):
                client.subscribe()
                last_subscription = now
            previous_app = app
        except Exception as exc:
            events_queue.put(("hub_error", str(exc)))
        if stop_event.wait(5):
            break


def consume_latest_sample(data_queue, history, connection_status, sample_index):
    message = drain_latest(data_queue)
    if message is None:
        return sample_index, None
    try:
        payload = build_payload_from_ws_message(message, sample_index=sample_index)
        metrics = payload["metrics"]
        if not metrics:  # Hub can send an empty packet before registration completes.
            return sample_index, None
        if training_extension_metric(metrics) is None and current_threshold(metrics) is None:
            raise ValueError("Packet has no finite hip angle or target; check the active Hub app")
        history.append(payload["time_sec"], metrics)
        connection_status.mark_packet()
        return sample_index + 1, metrics
    except (ValueError, TypeError, OverflowError) as exc:
        connection_status.data_error = str(exc)
        return sample_index, None


def run_viewer(
    hub_ip,
    port=DEFAULT_WS_PORT,
    history_sec=DEFAULT_HISTORY_SEC,
    draw_hz=10,
    stale_after_sec=DEFAULT_STALE_AFTER_SEC,
    api_port=80,
):
    import tkinter as tk

    data_queue = LatestValueQueue()
    events_queue = queue.Queue()
    stop_event = threading.Event()
    history = TrainingHistory(history_sec=history_sec)
    connection_status = ConnectionStatus(stale_after_sec=stale_after_sec)
    client = SageMotionWebSocketClient(hub_ip, port, REQUESTED_DATA, data_queue, events_queue, stop_event)

    root = tk.Tk()
    root.title("V{} IMU Hip Extension Viewer - {}:{}".format(VIEWER_VERSION, hub_ip, port))
    root.minsize(880, 460)
    canvas = FastTrainingCanvas(root, history, connection_status=connection_status)
    threading.Thread(target=client.run_forever, daemon=True).start()
    threading.Thread(target=monitor_hub_status,
                     args=(hub_ip, events_queue, stop_event, client, api_port), daemon=True).start()
    interval_ms = max(16, int(round(1000.0 / max(1.0, float(draw_hz)))))
    sample_index = 0

    def tick():
        nonlocal sample_index
        try:
            while True:
                try:
                    connection_status.apply_event(events_queue.get_nowait())
                except queue.Empty:
                    break
            sample_index, metrics = consume_latest_sample(data_queue, history, connection_status, sample_index)
            if metrics is not None:
                canvas.update_metrics(metrics)
            canvas.draw()
        except Exception as exc:
            connection_status.data_error = "{}: {}".format(type(exc).__name__, exc)
            canvas.status_var.set(connection_status.label())
        finally:
            if not stop_event.is_set():
                root.after(interval_ms, tick)

    def close_viewer():
        stop_event.set()
        root.destroy()
        threading.Thread(target=client.close, daemon=True).start()

    root.after(interval_ms, tick)
    root.protocol("WM_DELETE_WINDOW", close_viewer)
    root.mainloop()


def parse_args():
    parser = argparse.ArgumentParser(
        description="V{} Tkinter viewer for IMU hip-extension feedback.".format(VIEWER_VERSION)
    )
    parser.add_argument("--version", action="version",
                        version="V{} IMU Hip Extension Viewer (build {})".format(VIEWER_VERSION, VIEWER_BUILD))
    parser.add_argument("--hub-ip", default=HUB_DEFAULT_IP)
    parser.add_argument("--port", type=int, default=DEFAULT_WS_PORT)
    parser.add_argument("--api-port", type=int, default=80)
    parser.add_argument("--history-sec", type=float, default=DEFAULT_HISTORY_SEC)
    parser.add_argument("--draw-hz", type=float, default=10)
    parser.add_argument("--stale-after-sec", type=float, default=DEFAULT_STALE_AFTER_SEC)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_viewer(
        args.hub_ip,
        port=args.port,
        history_sec=args.history_sec,
        draw_hz=args.draw_hz,
        stale_after_sec=args.stale_after_sec,
        api_port=args.api_port,
    )
