"""Check the recording/stream schema without connecting to a Hub or motor."""
import importlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


APP = Path(__file__).resolve().parents[1] / "IMU_Hip_Extension_Feedback_v1_19_8vibrant"
INFO = json.loads((APP / "info.json").read_text(encoding="utf-8"))
SCHEMA = {field["name"]: field for field in INFO["user_fields"]}


class OfflineBaseApp:
    def __init__(self, sdk, filename):
        self.my_sage = sdk
        self.info = INFO
        self.config = json.loads((APP / "config.json").read_text(encoding="utf-8"))
        for key in ("training_command_udp_enabled", "debug_orientation_enabled",
                    "debug_orientation_udp_enabled", "debug_orientation_print_enabled"):
            self.config[key] = False


package = types.ModuleType("recording_v19_8")
package.__path__ = [str(APP)]
sage = types.ModuleType("sage")
base_app = types.ModuleType("sage.base_app")
base_app.BaseApp = OfflineBaseApp
with patch.dict(sys.modules, {"recording_v19_8": package, "sage": sage,
                              "sage.base_app": base_app}):
    core_module = importlib.import_module("recording_v19_8.core")


class StrictRecordingSDK:
    """Mirror the SDK's declared type check at both output boundaries."""
    def __init__(self):
        self.saved = None
        self.streamed = None

    def validate(self, payload):
        if set(payload) != set(SCHEMA):
            raise AssertionError("Recording fields differ from info.json")
        errors = []
        for name, field in SCHEMA.items():
            values = payload[name]
            expected = {"int": int, "float": float}[field["data_type"]]
            if len(values) != field["size"] or any(type(v) is not expected for v in values):
                errors.append("{}: {} expected {}".format(name, values, expected.__name__))
        if errors:
            raise AssertionError("\n".join(errors))

    def save_data(self, data, payload):
        self.validate(payload)
        self.saved = payload

    def send_stream_data(self, data, payload):
        self.validate(payload)
        self.streamed = payload


class RecordingTypeTests(unittest.TestCase):
    def setUp(self):
        self.sdk = StrictRecordingSDK()
        self.core = core_module.Core(self.sdk)

    def record(self):
        self.assertTrue(self.core.save_frame([{}, {}, {}, {}]))
        self.assertEqual(self.sdk.saved, self.sdk.streamed)
        self.assertEqual(len(self.sdk.saved), 155)
        return self.sdk.saved

    def test_initial_and_missing_monitor_frames_match_schema(self):
        self.record()
        self.core.vibration_measurement.update({}, 100.0)
        self.record()
        self.core.vibration_measurement.mark_recording_gap()
        self.record()

    def test_monitor_warmup_and_command_events_match_schema(self):
        monitor = self.core.vibration_measurement
        for index in range(12):
            monitor.begin_frame()
            monitor.update({"AccelX": 0, "AccelY": 0, "AccelZ": 9.81,
                            "Sampletime": index * 10, "Package": index},
                           monitor.origin + index / 100)
            self.record()
        self.assertEqual(monitor.metrics()["vibration_monitor_valid"], 1)
        # These methods record synthetic events only; no motor API is called.
        monitor.command_on(monitor.origin + 0.2, monitor.origin + 0.21, 0.2, 2)
        self.assertEqual(self.record()["vibration_command_duration_sec"], [0.2])
        monitor.command_off(monitor.origin + 0.4, monitor.origin + 0.41)
        self.record()
        monitor.command_error()
        self.record()

    def test_training_step_count_keeps_value_and_registered_float_type(self):
        monitor = self.core.vibration_measurement
        monitor.command_on(monitor.origin, monitor.origin, 0.2, 2)
        monitor.update({"AccelX": 0, "AccelY": 0, "AccelZ": 9.81,
                        "Sampletime": 0, "Package": 0}, monitor.origin)
        controller = self.core.adaptive_threshold_controller
        controller.mode = core_module.ADAPTIVE_MODE_TRAINING
        for count in range(1, 4):
            controller.update_training_step(True, True, 12.0)
            payload = self.record()
            self.assertEqual(payload["adaptive_eval_target_phase_sec"], [float(count)])
        controller.reset_training_window()
        self.assertEqual(self.record()["adaptive_eval_target_phase_sec"], [0.0])


if __name__ == "__main__":
    unittest.main()
