"""Replay lost, duplicate, delayed and recovered frames without any hardware."""
import types
import importlib.util
import unittest
from unittest.mock import patch

from test_v19_9_recording_types import APP, core_module, StrictRecordingSDK

spec = importlib.util.spec_from_file_location("v19_9_frame_guard_tests", APP / "frame_guard.py")
guard_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard_module)


def packet(tick, package):
    return [dict(SensorIndex=i, AccelX=0.0, AccelY=0.0, AccelZ=9.81,
                 GyroX=0.0, GyroY=0.0, GyroZ=0.0, MagX=0.0, MagY=0.0, MagZ=0.0,
                 Quat1=1.0, Quat2=0.0, Quat3=0.0, Quat4=0.0,
                 Sampletime=tick, Package=package) for i in range(4)]


class ClockGuardTests(unittest.TestCase):
    def setUp(self):
        self.guard = guard_module.FrameGuard(100, 4)

    def test_normal_samples_and_tick_and_package_wraps(self):
        self.assertTrue(self.guard.observe(packet(65530, 255), 10.0))
        self.assertTrue(self.guard.observe(packet(4, 0), 10.01))
        self.assertTrue(self.guard.observe(packet(14, 1), 10.02))
        self.assertEqual(self.guard.gap_count, 0)
        self.assertAlmostEqual(self.guard.sample_time_sec, 0.02)

    def test_single_missing_frame_is_a_gap(self):
        self.guard.observe(packet(0, 0), 10.0)
        self.assertFalse(self.guard.observe(packet(20, 2), 10.02))
        self.assertEqual(self.guard.reason, guard_module.SAMPLE_GAP)
        self.assertEqual(self.guard.gap_event, 1)
        self.assertTrue(self.guard.observe(packet(30, 3), 10.03))

    def test_repeated_tick_and_package_jump_cannot_count_as_fresh(self):
        self.guard.observe(packet(0, 0), 10.0)
        self.assertFalse(self.guard.observe(packet(0, 0), 10.01))
        self.assertEqual(self.guard.reason, guard_module.DUPLICATE)
        self.assertFalse(self.guard.observe(packet(10, 3), 10.02))
        self.assertEqual(self.guard.reason, guard_module.PACKAGE_GAP)

    def test_reverse_clock_latches_until_restart(self):
        self.guard.observe(packet(100, 10), 10.0)
        self.assertFalse(self.guard.observe(packet(90, 9), 10.01))
        self.assertFalse(self.guard.observe(packet(110, 11), 10.02))
        self.guard.reset()
        self.assertTrue(self.guard.observe(packet(110, 11), 10.02))

    def test_any_of_the_four_nodes_can_block_feedback(self):
        self.guard.observe(packet(0, 0), 10.0)
        frame = packet(10, 1)
        frame[3]["Sampletime"] = float("nan")
        self.assertFalse(self.guard.observe(frame, 10.01))
        self.assertEqual(self.guard.reason, guard_module.INVALID_CLOCK)

    def test_backlog_is_not_reanchored_as_fresh(self):
        self.guard.observe(packet(0, 0), 10.0)
        self.assertFalse(self.guard.observe(packet(10, 1), 10.2))
        for i in range(2, 10):
            self.assertFalse(self.guard.observe(packet(i * 10, i), 10.2 + (i - 1) * 0.001))
        self.assertGreater(self.guard.lag, 0.1)
        for i in range(10, 23):
            self.guard.observe(packet(i * 10, i), 10.2 + (i - 1) * 0.001)
        self.assertTrue(self.guard.fresh)
        self.assertEqual(self.guard.gap_count, 1)

    def test_command_boundary_rechecks_processing_age(self):
        self.guard.observe(packet(0, 0), 10.0)
        self.assertTrue(self.guard.can_actuate(10.01))
        self.assertFalse(self.guard.can_actuate(10.06))

    def test_receive_timeout_even_when_source_clock_advanced(self):
        self.guard.observe(packet(0, 0), 10.0)
        self.assertFalse(self.guard.observe(packet(200, 20), 10.2))
        self.assertEqual(self.guard.reason, guard_module.RECEIVE_TIMEOUT)


class ReplaySDK(StrictRecordingSDK):
    def __init__(self):
        super().__init__()
        self.frame = None
        self.commands = []
        self.records = []
        self.clear_count = 0

    def get_next_data(self):
        return self.frame

    def sensor_vibration_on(self, node, duration, strength):
        self.commands.append(("on", node, duration, strength))

    def sensor_vibration_off(self, node):
        self.commands.append(("off", node))

    def clear_buffered_data(self):
        self.clear_count += 1

    def save_data(self, data, payload):
        super().save_data(data, payload)
        self.records.append(payload)


class CoreReplayTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.angle = 0.0
        self.tick = -10
        self.package = -1
        self.clock_patch = patch.object(core_module.time, "monotonic", lambda: self.now)
        self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        self.sdk = ReplaySDK()
        self.core = core_module.Core(self.sdk)
        self.core.hip_calibrated = True
        self.core.standing_calibration.state = 3
        self.core.vibration_output_requested = False
        self.core.adaptive_threshold_controller.enabled = False
        self.core.adaptive_threshold_controller.mode = core_module.ADAPTIVE_MODE_DISABLED
        joints = types.SimpleNamespace(calculate_Hip_Flex=lambda *_: -self.angle)
        self.core.right_joint_angles = joints
        self.core.left_joint_angles = joints

    @property
    def pulses(self):
        return [c for c in self.sdk.commands if c[0] == "on"]

    def feed(self, angle, tick_step=10, wall_step=None, package_step=1, mutate=None):
        self.angle = angle
        self.tick = (self.tick + tick_step) % 65536
        self.package += package_step
        self.now += tick_step / 1000.0 if wall_step is None else wall_step
        self.sdk.frame = packet(self.tick, self.package)
        if mutate:
            mutate(self.sdk.frame)
        self.assertTrue(self.core.run_in_loop())
        return self.sdk.records[-1]

    def repeat(self, angle, count):
        for _ in range(count):
            self.feed(angle)

    def ready_with_20ms_target_dwell(self):
        self.repeat(0.0, 25)
        self.assertTrue(self.core.reward_controller.armed)
        self.repeat(12.0, 7)  # 5-point filter, then 20 ms above target.
        self.assertEqual(len(self.pulses), 0)
        self.assertAlmostEqual(self.core.frame_guard.sample_time_sec -
                               self.core.reward_controller.target_since, 0.02)

    def test_normal_cycle_gives_one_bounded_pulse_and_stops(self):
        self.ready_with_20ms_target_dwell()
        self.feed(12.0)
        self.assertEqual(self.pulses, [("on", 3, 0.2, 2)])
        self.repeat(12.0, 30)
        self.assertEqual(len(self.pulses), 1)
        self.assertIn(("off", 3), self.sdk.commands)

    def test_20ms_before_gap_cannot_be_completed_by_recovered_high_angle(self):
        self.ready_with_20ms_target_dwell()
        row = self.feed(12.0, tick_step=20, package_step=2)
        self.assertEqual(row["data_fresh_state"], [0])
        self.assertEqual(row["feedback_recovery_state"], [0])
        self.assertFalse(self.core.reward_controller.in_cycle)
        self.assertEqual(len(self.core.right_angle_window), 0)
        self.repeat(12.0, 50)
        self.assertEqual(len(self.pulses), 0)
        self.assertTrue(self.core.feedback_recovery_required)
        self.assertEqual(self.core.interrupted_episode_count, 1)
        self.assertEqual(self.sdk.records[-1]["feedback_recovery_state"], [1])

    def test_neutral_rearm_is_200ms_once_and_next_action_can_reward(self):
        self.ready_with_20ms_target_dwell()
        self.feed(12.0, tick_step=20, package_step=2)
        self.repeat(12.0, 5)
        self.repeat(0.0, 24)  # filter fills with neutral, then 190 ms.
        self.assertTrue(self.core.feedback_recovery_required)
        self.feed(0.0)  # Exactly 200 ms of fresh filtered neutral.
        self.assertFalse(self.core.feedback_recovery_required)
        self.assertTrue(self.core.reward_controller.armed)
        self.repeat(12.0, 8)
        self.assertEqual(len(self.pulses), 1)

    def test_duplicate_frame_breaks_dwell(self):
        self.ready_with_20ms_target_dwell()
        self.feed(12.0, tick_step=0, wall_step=0.01, package_step=0)
        self.repeat(12.0, 12)
        self.assertEqual(len(self.pulses), 0)
        self.assertTrue(self.core.feedback_recovery_required)

    def test_buffer_replay_is_logged_but_cannot_issue_old_rewards(self):
        self.ready_with_20ms_target_dwell()
        self.feed(12.0, wall_step=0.2)
        for _ in range(10):
            self.feed(12.0, wall_step=0.001)
        self.assertEqual(self.sdk.records[-1]["data_fresh_state"], [0])
        self.assertEqual(len(self.pulses), 0)
        for _ in range(20):
            self.feed(12.0, wall_step=0.001)
        self.assertEqual(self.sdk.records[-1]["data_fresh_state"], [1])
        self.assertTrue(self.core.feedback_recovery_required)
        self.assertEqual(len(self.pulses), 0)

    def test_invalid_pose_preserves_threshold_and_completed_statistics(self):
        self.ready_with_20ms_target_dwell()
        controller = self.core.adaptive_threshold_controller
        controller.enabled = True
        controller.mode = core_module.ADAPTIVE_MODE_TRAINING
        controller.window_valid_samples = controller._target_phase_samples = 7
        controller.window_success_samples = controller._success_samples = 5
        self.feed(12.0, mutate=lambda f: f[0].update(Quat1=0.0))
        self.repeat(12.0, 10)
        self.assertEqual(controller.window_valid_samples, 7)
        self.assertEqual(controller.window_success_samples, 5)
        self.assertEqual(self.core.min_threshold, 10.0)
        self.assertFalse(self.core.extension_peak_tracker.in_episode)
        self.assertEqual(len(self.pulses), 0)

    def test_start_discards_pretrial_buffer_and_requires_rearm(self):
        self.core.on_start_event(None)
        self.assertEqual(self.sdk.clear_count, 1)
        self.assertTrue(self.core.feedback_recovery_required)
        self.repeat(12.0, 30)
        self.assertEqual(len(self.pulses), 0)

    def test_consecutive_invalid_poses_are_one_interruption(self):
        self.ready_with_20ms_target_dwell()
        for _ in range(3):
            self.feed(12.0, mutate=lambda f: f[0].update(Quat1=0.0))
        self.assertEqual(self.core.frame_guard.gap_count, 1)
        self.feed(12.0)
        self.feed(12.0, mutate=lambda f: f[0].update(Quat1=0.0))
        self.assertEqual(self.core.frame_guard.gap_count, 2)

    def test_second_gap_restarts_the_neutral_rearm(self):
        self.ready_with_20ms_target_dwell()
        self.feed(12.0, tick_step=20, package_step=2)
        self.repeat(0.0, 20)
        self.assertTrue(self.core.feedback_recovery_required)
        self.feed(0.0, tick_step=20, package_step=2)
        self.repeat(0.0, 24)
        self.assertTrue(self.core.feedback_recovery_required)
        self.feed(0.0)
        self.assertFalse(self.core.feedback_recovery_required)
        self.assertEqual(len(self.pulses), 0)

    def test_gap_during_pulse_requests_off_and_never_replays_it(self):
        self.ready_with_20ms_target_dwell()
        self.feed(12.0)
        self.assertEqual(len(self.pulses), 1)
        self.feed(12.0, tick_step=20, package_step=2)
        self.assertEqual(self.sdk.commands[-1], ("off", 3))
        self.repeat(12.0, 40)
        self.assertEqual(len(self.pulses), 1)

    def test_processing_stall_cannot_complete_the_pending_target_dwell(self):
        self.ready_with_20ms_target_dwell()
        def slow_angle(*_):
            self.now += 0.06
            return -self.angle
        self.core.right_joint_angles = types.SimpleNamespace(calculate_Hip_Flex=slow_angle)
        row = self.feed(12.0)
        self.assertEqual(row["data_fresh_state"], [0])
        self.assertEqual(len(self.pulses), 0)
        self.assertTrue(self.core.feedback_recovery_required)

    def test_final_command_gate_refuses_data_that_aged_during_processing(self):
        self.repeat(0.0, 25)
        self.now += 0.06
        self.assertFalse(self.core.trigger_vibration(3, 0.2, 2))
        self.assertEqual(len(self.pulses), 0)
        self.assertTrue(self.core.feedback_recovery_required)

    def test_sample_time_in_recording_exposes_the_gap(self):
        self.repeat(0.0, 3)
        previous = self.sdk.records[-1]["time"][0]
        row = self.feed(0.0, tick_step=20, package_step=2)
        self.assertAlmostEqual(row["time"][0] - previous, 0.02)
        self.assertEqual(row["data_gap_event"], [1])


if __name__ == "__main__":
    unittest.main()
