"""Regression checks for blank charts, reconnects and calibration feedback."""
import importlib.util
import json
from pathlib import Path
import queue
import sys
import threading
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("viewer_v19_9", ROOT / "fast_imu_training_viewer_v19_9.py")
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)


def hub_packet(timestamp=42.12, angle=68.53, calibrated=1):
    # Shape and values observed from the user's SageOS 4.8.23 stream.
    return json.dumps({
        "custom_data": {
            "time": [timestamp],
            "filtered_selected_Hip_ext": [angle],
            "selected_hip_signed_extension_deg": [-angle],
            "adaptive_current_threshold": [10.0],
            "adaptive_mode_state": [1],
            "adaptive_assessed_threshold": [0.0],
            "adaptive_assessment_elapsed_sec": [0.0],
            "hip_calibrated_state": [calibrated],
            "standing_calibration_state": [3 if calibrated else 2],
            "standing_stable_elapsed_sec": [2.0 if calibrated else 0.4],
            "data_valid_state": [1],
            "data_fresh_state": [1],
            "feedback_recovery_state": [2],
        },
        "raw_data": [{}, {}, {}, {}],
        "time_stamp_in_milliseconds": timestamp * 1000,
    })


class StreamRegressionTests(unittest.TestCase):
    def setUp(self):
        self.data = viewer.LatestValueQueue()
        self.history = viewer.TrainingHistory()
        self.status = viewer.ConnectionStatus()
        self.status.apply_event(("connected", "ws://hub:5678/"))

    def consume(self, message, index=0):
        self.data.put(message)
        return viewer.consume_latest_sample(self.data, self.history, self.status, index)

    def test_real_hub_shape_reaches_angle_and_target_history(self):
        index, metrics = self.consume(hub_packet())
        self.assertEqual(index, 1)
        self.assertAlmostEqual(self.history.extensions[-1], -68.53)
        self.assertEqual(self.history.thresholds[-1], 10.0)
        self.assertTrue(viewer.app_schema_is_current(metrics))

    def test_empty_registration_packet_does_not_count_as_live(self):
        index, metrics = self.consume('{"custom_data": {}, "raw_data": [{}, {}, {}, {}]}')
        self.assertEqual((index, metrics), (0, None))
        self.assertEqual(self.status.packet_count, 0)

    def test_bad_packet_does_not_prevent_next_valid_sample(self):
        index, metrics = self.consume('not json')
        self.assertIsNone(metrics)
        self.assertTrue(self.status.data_error)
        index, metrics = self.consume(hub_packet(), index)
        self.assertEqual(index, 1)
        self.assertEqual(self.status.data_error, "")

    def test_errors_survive_close_callback_and_buffered_old_sample(self):
        self.status.apply_event(("error", "connection refused"))
        self.status.apply_event(("closed", "WebSocket closed"))
        self.consume(hub_packet())
        self.assertIn("connection refused", self.status.label())
        self.status.apply_event(("connected", "ws://hub:5678/"))
        self.assertNotIn("connection refused", self.status.label())

    def test_calibration_and_ready_are_visible(self):
        self.status.apply_event(("hub", {"app_state": "CONFIGURE"}))
        self.assertIn("CONFIGURE", viewer.viewer_prompt(self.status, {})[0])
        self.status.apply_event(("hub", {"app_state": "READY"}))
        self.assertIn("Start", viewer.viewer_prompt(self.status, {})[0])
        self.status.apply_event(("hub", {"app_state": "RUNNING"}))
        _, metrics = self.consume(hub_packet(angle=0.0, calibrated=0))
        self.assertIn("站立校准", viewer.viewer_prompt(self.status, metrics)[0])
        _, metrics = self.consume(hub_packet())
        self.assertIn("校准完成", viewer.viewer_prompt(self.status, metrics)[0])

    def test_app_restart_clears_previous_trial_trace(self):
        self.consume(hub_packet(42.0))
        self.consume(hub_packet(0.01, angle=2.0), 1)
        self.assertEqual(list(self.history.times), [0.01])
        self.assertEqual(list(self.history.extensions), [-2.0])

    def test_running_but_stalled_stream_reports_interruption(self):
        self.status.apply_event(("hub", {"app_state": "RUNNING"}))
        self.assertIn("等待有效角度数据", viewer.viewer_prompt(self.status, {})[0])
        _, metrics = self.consume(hub_packet())
        self.status.last_packet_wall_time -= self.status.stale_after_sec + 1
        prompt, color = viewer.viewer_prompt(self.status, metrics)
        self.assertIn("实时数据已中断", prompt)
        self.assertIn("重新连接传感器", prompt)
        self.assertEqual(color, "#b00020")

    def test_nonfinite_values_do_not_crash_numeric_display(self):
        for value in (float('nan'), float('inf'), '-inf'):
            self.assertIsNone(viewer.metric_float({'x': value}, 'x'))
            self.assertEqual(viewer.metric_int({'x': value}, 'x', -1), -1)

    def test_subscriptions_exist_in_v19_9_schema(self):
        info = json.loads((ROOT / 'IMU_Hip_Extension_Feedback_v1_19_9vibrant' / 'info.json').read_text(encoding='utf-8'))
        names = {field['name'] for field in info['user_fields']}
        self.assertFalse(set(viewer.METRIC_FIELDS) - names)

    def test_gap_recovery_and_old_app_are_visible(self):
        _, metrics = self.consume(hub_packet())
        metrics.update(data_fresh_state=0, data_gap_reason=4, data_gap_count=1)
        self.assertIsNone(viewer.training_extension_metric(metrics))
        self.assertIn("奖励已暂停", viewer.viewer_prompt(self.status, metrics)[0])
        metrics.update(data_fresh_state=1, feedback_recovery_state=1,
                       feedback_recovery_neutral_sec=0.1)
        self.assertIn("100 ms", viewer.viewer_prompt(self.status, metrics)[0])
        del metrics["data_fresh_state"]
        self.assertIn("缺少 V19.9v", viewer.viewer_prompt(self.status, metrics)[0])

    def test_chart_does_not_join_angles_across_a_gap(self):
        lines = []
        fake = types.SimpleNamespace(create_line=lambda *coords, **kwargs: lines.append(coords))
        instance = types.SimpleNamespace(canvas=fake)
        viewer.FastTrainingCanvas._draw_polyline(instance, [1.0, 2.0, None, 3.0, 4.0],
                                                lambda i, value: (i, value), "blue")
        self.assertEqual(lines, [(0, 1.0, 1, 2.0), (3, 3.0, 4, 4.0)])

    def test_viewer_version_and_hub_version_are_visible(self):
        self.assertEqual(viewer.VIEWER_VERSION, "19.9v")
        self.assertEqual(viewer.VIEWER_BUILD, "901900")
        self.status.apply_event(("hub", {"app_state": "RUNNING",
                                        "app_version_id": "9011_19_9vibrant"}))
        self.assertEqual(self.status.app_version_id, "9011_19_9vibrant")

    def test_disconnect_reconnects_and_resubscribes(self):
        class FastStop(threading.Event):
            def wait(self, timeout=None):
                return self.is_set()
        stop = FastStop()
        events = queue.Queue()
        sent = []
        attempts = []
        class FakeSocketApp:
            def __init__(self, url, **callbacks):
                self.callbacks = callbacks
                attempts.append(url)
            def send(self, message):
                sent.append(json.loads(message))
            def run_forever(self, **options):
                self.callbacks['on_open'](self)
                if len(attempts) == 1:
                    self.callbacks['on_error'](self, RuntimeError('link lost'))
                    self.callbacks['on_close'](self, 1006, '')
                else:
                    self.callbacks['on_message'](self, hub_packet())
                    stop.set()
        fake = types.SimpleNamespace(WebSocketApp=FakeSocketApp, setdefaulttimeout=lambda _: None)
        client = viewer.SageMotionWebSocketClient('hub', 5678, viewer.REQUESTED_DATA, self.data, events, stop)
        with patch.dict(sys.modules, {'websocket': fake}):
            client.run_forever()
        self.assertEqual(len(attempts), 2)
        self.assertEqual(sent, [viewer.REQUESTED_DATA, viewer.REQUESTED_DATA])
        self.assertEqual(viewer.consume_latest_sample(self.data, self.history, self.status, 0)[0], 1)

    def test_actual_tk_canvas_draws_both_curves_and_keeps_error_visible(self):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            canvas = viewer.FastTrainingCanvas(root, self.history, self.status)
            for i in range(8):
                _, metrics = self.consume(hub_packet(42 + i / 10, 68 + i))
            canvas.update_metrics(metrics)
            canvas.draw()
            self.assertIn("Viewer v19.9v", canvas.status_var.get())
            line_colors = {canvas.canvas.itemcget(item, 'fill')
                           for item in canvas.canvas.find_all()
                           if canvas.canvas.type(item) == 'line'}
            self.assertIn('#1f77b4', line_colors)
            self.assertIn('#2ca02c', line_colors)
            self.status.apply_event(('error', 'link lost'))
            canvas.draw()
            self.assertIn('link lost', canvas.status_var.get())
            self.assertIn('link lost', canvas.prompt_var.get())
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
