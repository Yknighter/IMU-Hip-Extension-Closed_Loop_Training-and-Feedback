import json
import time
import socket
import numpy as np
from collections import deque
from sage.base_app import BaseApp
from .Rotation import Rotation as R
from .JointAngles import JointAngles
from .YawCorrection import YawCorrection
from .standing_calibration import StandingCalibration
from .orientation_debug import (
    build_orientation_payload,
    encode_orientation_packet,
    format_orientation_summary,
    should_emit_debug,
)
from .adaptive_threshold import (
    MODE_ASSESSMENT as ADAPTIVE_MODE_ASSESSMENT,
    MODE_DISABLED as ADAPTIVE_MODE_DISABLED,
    MODE_TRAINING as ADAPTIVE_MODE_TRAINING,
    AdaptiveThresholdController,
)
from .calibration_controller import (
    CALIBRATION_COLLECTING,
    CALIBRATION_CONFIRMED,
    CALIBRATION_DISABLED,
    CALIBRATION_READY,
    CalibrationController,
)
from .progressive_vibration import ProgressiveVibrationController
from .gait_phase_controller import (
    GAIT_STANCE,
    GAIT_SWING,
    GAIT_UNKNOWN,
    LEVEL_ABOVE,
    LEVEL_BELOW,
    LEVEL_UNKNOWN,
    LEVEL_WITHIN,
    STANCE_FOOT_FLAT,
    STANCE_HEEL_OFF,
    STANCE_HEEL_STRIKE,
    STANCE_MID,
    STANCE_NONE,
    STANCE_TOE_OFF,
    SWING_ACCELERATION,
    SWING_DECELERATION,
    SWING_MID,
    SWING_NONE,
    GaitPhaseController,
)
from .deficit_feedback_strategy import (
    LEVEL_FAR as ANGLE_LEVEL_BELOW,
    LEVEL_NEAR as ANGLE_LEVEL_WITHIN,
    LEVEL_SUCCESS as ANGLE_LEVEL_ABOVE,
    LEVEL_UNKNOWN as ANGLE_LEVEL_UNKNOWN,
    STATE_ARMED as DEFICIT_STATE_ARMED,
    STATE_DISARMED as DEFICIT_STATE_DISARMED,
    STATE_SUCCESS_LATCHED as DEFICIT_STATE_SUCCESS_LATCHED,
    DeficitFeedbackStrategy,
)
from .local_peak_tracker import ExtensionPeakCycleTracker
from .reward_feedback import (
    RewardFeedbackController, PULSE_REWARD, MAX_REWARD_PULSE_DURATION_SEC,
    validate_vibration_strength,
)
from .vibration_measurement import VibrationMeasurement

FEEDBACK_OFF = 0
FEEDBACK_ON = 1
PHASE_WAITING = 0
PHASE_EXTENDING = 1
PHASE_QUALIFIED = 2
APP_SCHEMA_VERSION = 1197
ADAPTIVE_SCHEMA_VERSION = 6

def get_bool(config, key, default=False):
    value = config.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def target_direction_from_feedback_trigger(direction):
    return "increasing" if direction == "below" else "decreasing"

def get_rotation(data, node_num):
    return R.from_quat(
        [
            data[node_num]["Quat1"],
            data[node_num]["Quat2"],
            data[node_num]["Quat3"],
            data[node_num]["Quat4"],
        ],
        scalar_first=True,
    )


class Core(BaseApp):
    ###########################################################
    # INITIALIZE APP
    ###########################################################
    def __init__(self, my_sage):
        BaseApp.__init__(self, my_sage, __file__)

        # One participant comfort setting applies to every reward in this run.
        self.feedback_strength = validate_vibration_strength(
            self.config.get("reward_strength", 2))
        self.DATARATE = self.info["datarate"]
        self.pulse_length = self.info["pulse_length"]
        self.min_threshold = float(self.config["min_threshold"])
        self.max_threshold = float(self.config.get("max_threshold", 20.0))
        self.feedback_mode = self.config.get("feedback_mode", "angle")
        self.feedback_trigger_direction = self.config.get(
            "feedback_trigger_direction", "below"
        )
        self.training_leg = str(self.config.get("training_leg", "right")).lower()
        if self.training_leg not in ("right", "left"):
            self.training_leg = "right"
        self.training_leg_state = 1 if self.training_leg == "right" else 2
        self.phase_gate_enabled = get_bool(self.config, "phase_gate_enabled", True)
        self.right_phase_threshold = float(self.config.get("right_phase_threshold", -90.0))
        self.right_phase_direction = self.config.get("right_phase_direction", "above")
        self.left_forward_threshold = float(self.config.get("left_forward_threshold", 0.0))
        self.left_forward_direction = self.config.get("left_forward_direction", "above")
        self.left_back_threshold = float(self.config.get("left_back_threshold", self.right_phase_threshold))
        self.left_back_direction = self.config.get("left_back_direction", self.right_phase_direction)
        self.right_forward_threshold = float(self.config.get("right_forward_threshold", self.left_forward_threshold))
        self.right_forward_direction = self.config.get("right_forward_direction", self.left_forward_direction)
        self.extension_direction = self.config.get("extension_direction", "decreasing")
        self.extension_velocity_threshold = float(
            self.config.get("extension_velocity_threshold", 0.05)
        )
        self.reset_velocity_threshold = float(
            self.config.get("reset_velocity_threshold", 0.05)
        )
        self.trend_window_samples = max(
            2,
            int(float(self.config.get("trend_window_ms", 400)) * self.DATARATE / 1000),
        )
        self.extension_trend_threshold = float(
            self.config.get("extension_trend_threshold", 1.0)
        )
        self.reset_trend_threshold = float(
            self.config.get("reset_trend_threshold", 1.0)
        )
        self.hysteresis_deg = float(self.config.get("hysteresis_deg", 2.0))
        self.movement_gate_enabled = get_bool(self.config, "movement_gate_enabled", False)
        self.movement_gate_gyro_threshold = float(
            self.config.get("movement_gate_gyro_threshold", 20.0)
        )
        self.calibration_enabled = (
            get_bool(self.config, "calibration_enabled", False)
            and self.feedback_mode == "angle"
        )
        self.calibration_controller = CalibrationController(
            enabled=self.calibration_enabled,
            duration_sec=float(self.config.get("calibration_duration_sec", 30.0)),
            min_target_phase_sec=float(
                self.config.get("calibration_min_target_phase_sec", 5.0)
            ),
            min_steps=int(self.config.get("calibration_min_steps", 8)),
            percentile=float(self.config.get("calibration_percentile", 0.6)),
            target_offset_deg=float(
                self.config.get("calibration_target_offset_deg", 0.5)
            ),
            limit=float(self.config.get("adaptive_threshold_limit", 15.0)),
            direction=self.config.get("adaptive_threshold_direction", "increasing"),
            datarate=self.DATARATE,
            max_duration_sec=float(
                self.config.get("calibration_max_duration_sec", 30.0)
            ),
        )
        self.training_command_udp_enabled = get_bool(
            self.config, "training_command_udp_enabled", True
        )
        self.training_command_udp_port = int(
            self.config.get("training_command_udp_port", 50516)
        )
        self.training_command_socket = None
        self.training_command_received_count = 0
        self.training_command_last_error_code = 0
        if self.training_command_udp_enabled:
            self.training_command_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.training_command_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.training_command_socket.setblocking(False)
            try:
                self.training_command_socket.bind(("0.0.0.0", self.training_command_udp_port))
            except OSError as exc:
                self.training_command_last_error_code = int(exc.errno or -1)
                self.training_command_socket = None
        self.progressive_vibration_enabled = get_bool(
            self.config, "progressive_vibration_enabled", True
        )
        self.threshold_target_direction = target_direction_from_feedback_trigger(
            self.feedback_trigger_direction
        )
        self.vibration_controller = ProgressiveVibrationController(
            enabled=self.progressive_vibration_enabled,
            min_interval_ms=float(self.config.get("progressive_min_interval_ms", 250)),
            max_interval_ms=float(self.config.get("progressive_max_interval_ms", 3000)),
            curve=float(self.config.get("progressive_interval_curve", 1.2)),
            pulse_duration=float(self.config.get("vibration_pulse_duration", 5)),
            strength=self.feedback_strength,
            terminal_feedback_mode=self.config.get("terminal_feedback_mode", "single_pulse"),
            direction=self.config.get("adaptive_threshold_direction", "increasing"),
            datarate=self.DATARATE,
        )
        self.graded_vibration_enabled = (
            get_bool(self.config, "graded_vibration_enabled", True)
            and self.feedback_mode == "angle"
        )
        self.angle_graded_feedback_enabled = (
            get_bool(self.config, "angle_graded_feedback_enabled", True)
            and self.feedback_mode == "angle"
        )
        self.deficit_feedback_enabled = (
            get_bool(self.config, "deficit_feedback_enabled", True)
            and self.feedback_mode == "angle"
        )
        self.ability_range_min_deg = float(
            self.config.get("ability_range_min_deg", 5.0)
        )
        self.ability_range_max_deg = float(
            self.config.get("ability_range_max_deg", 7.0)
        )
        self.initial_feedback_level = int(self.config.get("initial_feedback_level", 2))
        self.gait_controller = GaitPhaseController(
            datarate=self.DATARATE,
            min_stance_ms=float(self.config.get("gait_min_stance_ms", 250)),
            min_swing_ms=float(self.config.get("gait_min_swing_ms", 250)),
            mid_stance_fraction=float(
                self.config.get("gait_mid_stance_fraction", 0.5)
            ),
            swing_deceleration_fraction=float(
                self.config.get("gait_swing_deceleration_fraction", 0.7)
            ),
            ability_range_min_deg=self.ability_range_min_deg,
            ability_range_max_deg=self.ability_range_max_deg,
            direction=self.config.get("adaptive_threshold_direction", "increasing"),
            initial_feedback_level=self.initial_feedback_level,
        )
        self.deficit_feedback_strategy = DeficitFeedbackStrategy(
            enabled=self.deficit_feedback_enabled,
            datarate=self.DATARATE,
            target_direction=self.threshold_target_direction,
            near_margin_deg=float(self.config.get("deficit_near_margin_deg", 5.0)),
            far_margin_deg=float(self.config.get("deficit_far_margin_deg", 10.0)),
            reset_margin_deg=float(self.config.get("deficit_reset_margin_deg", 5.0)),
            target_dwell_ms=float(self.config.get("deficit_target_dwell_ms", 120)),
            reset_dwell_ms=float(self.config.get("deficit_reset_dwell_ms", 250)),
            success_refractory_ms=float(
                self.config.get("deficit_success_refractory_ms", 800)
            ),
            level1_interval_ms=float(
                self.config.get("deficit_level1_interval_ms", 800)
            ),
            level1_duration=float(self.config.get("deficit_level1_duration", 0.2)),
            level1_strength=self.feedback_strength,
            level2_min_interval_ms=float(
                self.config.get("deficit_level2_min_interval_ms", 250)
            ),
            level2_max_interval_ms=float(
                self.config.get("deficit_level2_max_interval_ms", 700)
            ),
            level2_duration=float(self.config.get("deficit_level2_duration", 0.2)),
            level2_strength=self.feedback_strength,
            level3_duration=float(self.config.get("deficit_level3_duration", 0.8)),
            level3_strength=self.feedback_strength,
            success_vibration_enabled=get_bool(
                self.config, "deficit_success_vibration_enabled", False
            ),
        )
        self.default_deficit_reset_margin_deg = float(
            self.deficit_feedback_strategy.reset_margin_deg
        )
        self.initial_min_threshold = self.min_threshold
        self.adaptive_threshold_requested = get_bool(
            self.config, "adaptive_threshold_enabled", False
        )
        self.adaptive_threshold_enabled = (
            self.adaptive_threshold_requested and self.feedback_mode == "angle"
        )
        self.adaptive_threshold_controller = AdaptiveThresholdController(
            enabled=self.adaptive_threshold_enabled,
            initial_threshold=self.initial_min_threshold,
            limit=float(self.config.get("adaptive_threshold_limit", 15.0)),
            step_deg=float(self.config.get("adaptive_step_deg", 1.0)),
            direction=self.config.get("adaptive_threshold_direction", "increasing"),
            interval_sec=float(self.config.get("adaptive_interval_sec", 60.0)),
            success_ratio_required=float(
                self.config.get("adaptive_success_ratio_required", 0.8)
            ),
            min_target_phase_sec=float(
                self.config.get("adaptive_min_target_phase_sec", 10.0)
            ),
            datarate=self.DATARATE,
            assessment_sec=float(self.config.get("adaptive_assessment_sec", 60.0)),
            assessment_percentile=float(
                self.config.get("adaptive_assessment_percentile", 0.75)
            ),
            assessment_rounding=self.config.get(
                "adaptive_assessment_rounding", "floor"
            ),
            min_start_threshold=float(
                self.config.get("adaptive_min_start_threshold", 1.0)
            ),
            min_valid_steps_per_window=int(
                self.config.get("adaptive_min_valid_steps_per_window", 8)
            ),
        )
        self.extension_peak_tracker = ExtensionPeakCycleTracker(
            datarate=self.DATARATE,
            min_extension_episode_ms=float(
                self.config.get("adaptive_min_extension_episode_ms", 200)
            ),
            extension_episode_end_dwell_ms=float(
                self.config.get("adaptive_extension_episode_end_dwell_ms", 200)
            ),
            min_valid_peak_deg=float(
                self.config.get("adaptive_min_valid_peak_deg", 0.5)
            ),
        )
        self.adaptive_current_level = 1
        self.adaptive_mode_state = ADAPTIVE_MODE_DISABLED
        self.adaptive_assessed_threshold = 0.0
        self.adaptive_assessment_elapsed_sec = 0.0
        self.adaptive_assessment_sample_count = 0
        self.adaptive_assessment_extension_sample_count = 0
        self.adaptive_level_up_event_state = FEEDBACK_OFF
        self.adaptive_success_ratio_percent = 0.0
        self.adaptive_window_success_samples = 0
        self.adaptive_window_valid_samples = 0
        self.adaptive_last_window_success_samples = 0
        self.adaptive_last_window_valid_samples = 0
        self.adaptive_latest_step_peak_deg = 0.0
        self.adaptive_current_step_peak_deg = 0.0
        self.adaptive_last_step_peak_deg = 0.0
        self.adaptive_last_step_success_state = FEEDBACK_OFF
        self.adaptive_last_step_valid_state = FEEDBACK_OFF
        self.adaptive_last_step_reject_reason = 0
        self.adaptive_min_valid_steps_per_window_state = int(
            self.adaptive_threshold_controller.min_target_phase_samples
        )
        self.adaptive_step_deg_state = float(
            self.adaptive_threshold_controller.step_deg
        )
        self.sync_adaptive_display_state()
        self.debug_orientation_enabled = get_bool(
            self.config, "debug_orientation_enabled", False
        )
        self.debug_orientation_print_enabled = get_bool(
            self.config,
            "debug_orientation_print_enabled",
            self.debug_orientation_enabled,
        )
        self.debug_orientation_udp_enabled = get_bool(
            self.config, "debug_orientation_udp_enabled", False
        )
        self.debug_orientation_hz = float(
            self.config.get("debug_orientation_hz", 5.0)
        )
        self.debug_orientation_udp_host = self.config.get(
            "debug_orientation_udp_host", "192.168.12.255"
        )
        self.debug_orientation_udp_port = int(
            self.config.get("debug_orientation_udp_port", 50514)
        )
        self.debug_orientation_socket = None
        self.debug_orientation_udp_send_count = 0
        self.debug_orientation_udp_error_count = 0
        self.debug_orientation_udp_last_error_code = 0
        self.debug_orientation_udp_target_last_octet = self.get_udp_host_last_octet(
            self.debug_orientation_udp_host
        )
        if self.debug_orientation_udp_enabled:
            self.debug_orientation_socket = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM
            )
            self.debug_orientation_socket.setsockopt(
                socket.SOL_SOCKET, socket.SO_BROADCAST, 1
            )
        self.cooldown_iters = max(
            1, int(float(self.config.get("cooldown_ms", 250)) * self.DATARATE / 1000)
        )
        self.moving_average_window = max(
            1, int(self.config.get("moving_average_window", 5))
        )

        self.NodeNum_right_thigh = self.info["sensors"].index("right_thigh")
        self.NodeNum_left_thigh = self.info["sensors"].index("left_thigh")
        self.NodeNum_pelvis = self.info["sensors"].index("pelvis")
        self.NodeNum_vibration_monitor = self.info["sensors"].index("vibration_monitor")
        self.vibration_measurement = VibrationMeasurement(
            self.DATARATE, time.monotonic(),
            threshold=float(self.config.get("vibration_detection_threshold_mps2", 0)),
            highpass_hz=float(self.config.get("vibration_highpass_hz", 10)),
            window_ms=float(self.config.get("vibration_rms_window_ms", 50)),
            tolerance_sec=float(self.config.get("vibration_match_tolerance_sec", 0.15)),
        )
        self.vibration_output_requested = None
        self.NodeNum_feedback_front = (
            self.info["feedback"].index("feedback_front")
            if "feedback_front" in self.info["feedback"]
            else None
        )
        self.NodeNum_feedback_max = (
            self.info["feedback"].index("feedback_max")
            if "feedback_max" in self.info["feedback"]
            else None
        )

        self.iteration = 0
        self.app_schema_version = APP_SCHEMA_VERSION
        self.adaptive_schema_version = ADAPTIVE_SCHEMA_VERSION
        self.right_joint_angles = JointAngles(True)
        self.left_joint_angles = JointAngles(False)
        # Both yaw alignment and hip zero use the accepted stable standing pose.
        self.yaw_correction = None
        self.yaw_offsets = [0.0] * len(self.info["sensors"])
        self.yaw_offsets[self.NodeNum_right_thigh] = 90.0
        self.yaw_offsets[self.NodeNum_left_thigh] = -90.0
        self.standing_calibration = StandingCalibration(
            self.DATARATE, duration=2.0,
            tolerance_deg=float(self.config.get("standing_stability_tolerance_deg", 2.0)),
            step_deg=float(self.config.get("standing_stability_step_deg", 0.5)),
        )
        self.hip_calibrated = False
        self.right_Hip_ext = 0.0
        self.left_Hip_ext = 0.0
        self.filtered_right_Hip_ext = 0.0
        self.filtered_left_Hip_ext = 0.0
        self.right_gyro_mag = 0.0
        self.left_gyro_mag = 0.0
        self.right_acc_mag = 0.0
        self.left_acc_mag = 0.0
        self.feedback_metric = 0.0
        self.feedback_mode_code = 0
        self.feedback_reason_code = 0
        self.right_leg_back_state = FEEDBACK_OFF
        self.left_leg_back_state = FEEDBACK_OFF
        self.right_leg_forward_state = FEEDBACK_OFF
        self.left_leg_forward_state = FEEDBACK_OFF
        self.target_leg_back_state = FEEDBACK_OFF
        self.opposite_leg_forward_state = FEEDBACK_OFF
        self.target_phase_state = FEEDBACK_OFF
        self.selected_Hip_ext = 0.0
        self.filtered_selected_Hip_ext = 0.0
        self.selected_hip_signed_extension_deg = 0.0
        self.selected_hip_forward_side_state = FEEDBACK_OFF
        self.selected_hip_extension_side_state = FEEDBACK_OFF
        self.right_hip_velocity = 0.0
        self.right_hip_trend = 0.0
        self.right_hip_extending_state = FEEDBACK_OFF
        self.right_hip_flexing_state = FEEDBACK_OFF
        self.selected_hip_velocity = 0.0
        self.selected_hip_trend = 0.0
        self.selected_hip_extending_state = FEEDBACK_OFF
        self.selected_hip_flexing_state = FEEDBACK_OFF
        self.feedback_phase_state = PHASE_WAITING
        self.previous_filtered_selected_Hip_ext = None
        self.previous_feedback_raw_hip_ext = None
        self.last_deficit_feedback_decision = None
        self.last_forward_level1_feedback_iter = None
        self.deficit_forward_rearm_started_iter = None
        self.previous_filtered_right_Hip_ext = None

        self.right_thigh_quat = None
        self.left_thigh_quat = None
        self.right_angle_window = deque(maxlen=self.moving_average_window)
        self.left_angle_window = deque(maxlen=self.moving_average_window)
        self.selected_trend_window = deque(maxlen=self.trend_window_samples)
        self.right_trend_window = self.selected_trend_window

        self.alreadyGivenFeedback = 0        
        self.min_feedback_state = FEEDBACK_OFF
        self.max_feedback_state = FEEDBACK_OFF
        self.threshold_met_state = FEEDBACK_OFF
        self.feedback_progress_ratio = 0.0
        self.feedback_interval_ms = float(self.vibration_controller.min_interval_ms)
        self.terminal_goal_met_state = FEEDBACK_OFF
        self.gait_cycle_index = 0
        self.gait_phase_state = GAIT_UNKNOWN
        self.stance_phase_state = STANCE_NONE
        self.swing_phase_state = SWING_NONE
        self.heel_strike_event_state = FEEDBACK_OFF
        self.mid_stance_event_state = FEEDBACK_OFF
        self.toe_off_event_state = FEEDBACK_OFF
        self.swing_deceleration_state = FEEDBACK_OFF
        self.current_cycle_peak_extension = 0.0
        self.previous_cycle_peak_extension = 0.0
        self.previous_cycle_feedback_level = LEVEL_UNKNOWN
        self.current_feedback_level = self.initial_feedback_level
        self.posterior_feedback_state = FEEDBACK_OFF
        self.front_feedback_state = FEEDBACK_OFF
        self.angle_feedback_level = ANGLE_LEVEL_UNKNOWN
        self.angle_limit_burst_count = 0
        self.angle_limit_burst_remaining = 0
        self.angle_limit_latched_state = FEEDBACK_OFF
        self.deficit_feedback_deficit_deg = 0.0
        self.deficit_feedback_machine_state = DEFICIT_STATE_DISARMED
        self.deficit_feedback_armed_state = FEEDBACK_OFF
        self.deficit_feedback_success_latched_state = FEEDBACK_OFF
        self.deficit_feedback_target_dwell_state = FEEDBACK_OFF
        self.deficit_feedback_reset_dwell_state = FEEDBACK_OFF
        self.adaptive_current_step_peak_deg = 0.0
        self.adaptive_last_step_peak_deg = 0.0
        self.adaptive_last_step_success_state = FEEDBACK_OFF
        self.adaptive_last_step_valid_state = FEEDBACK_OFF
        self.adaptive_last_step_reject_reason = 0
        self.vibration_total_count = 0
        self.vibration_recent_count_60s = 0
        self.vibration_rate_per_min_60s = 0.0
        self.vibration_last_duration_sec = 0.0
        self.vibration_last_strength = 0
        self.vibration_interval_ms_state = 0.0
        self.vibration_frequency_hz_state = 0.0
        self.vibration_recent_window_sec = 60.0
        self.vibration_event_iters = deque()
        self.active_min_feedback_until_iter = None
        self.active_front_feedback_until_iter = None
        self.last_min_feedback_iter = -self.cooldown_iters
        self.last_max_feedback_iter = -self.cooldown_iters
        self.reward_controller = RewardFeedbackController(
            self.DATARATE,
            target_dwell_ms=float(self.config.get("reward_target_dwell_ms", 30)),
            rearm_ms=float(self.config.get("adaptive_extension_episode_end_dwell_ms", 200)),
            duration=float(self.config.get("reward_pulse_duration", 0.2)),
            strength=self.feedback_strength,
        )
        if self.feedback_mode != "angle" or self.threshold_target_direction != "increasing":
            raise ValueError("V19_7vibrant rewards require angle mode and increasing positive extension targets")
        if not np.isfinite(self.min_threshold) or self.min_threshold <= 0:
            raise ValueError("The reward target must be positive and finite")
        self.reward_qualified_event = 0
        self.reward_sent_event = 0
        self.reward_suppressed_event = 0
        self.local_peak_event_state = 0
        self.local_peak_latest_deg = 0.0
        self.local_peak_sample = -1
        self.local_peak_confirmed_sample = -1
        self.last_episode_candidate_count = 0
        self.peak_target_met_event = 0
        self.data_valid_state = 1
        self.invalid_frame_count = 0

    ###########################################################
    # CHECK NODE CONNECTIONS
    ###########################################################
    def _mean_quat(self, quat_samples) -> R:
        if not quat_samples:
            raise ValueError("quat_samples must not be empty")
        q0 = np.array(quat_samples[0], dtype=float)
        A = np.zeros((4, 4), dtype=float)
        for q in quat_samples:
            q = np.array(q, dtype=float)
            if np.dot(q0, q) < 0.0:
                q = -q
            A += np.outer(q, q)
        _, eigvecs = np.linalg.eigh(A)
        q_avg = eigvecs[:, -1]
        if np.dot(q_avg, q0) < 0.0:
            q_avg = -q_avg
        return R.from_quat(q_avg, scalar_first=True)

    def check_status(self):
        sensors_count = self.get_sensors_count()
        feedback_count = self.get_feedback_count()
        err_msg = ""
        if not all(callable(getattr(self.my_sage, name, None)) for name in
                   ("sensor_vibration_on", "sensor_vibration_off")):
            err_msg += "App requires the modern sensor_vibration_on/off API. "
        if sensors_count < len(self.info["sensors"]):
            err_msg += "App requires {} sensors but only {} are connected".format(
                len(self.info["sensors"]), sensors_count
            )
        if self.config["feedback_enabled"] and feedback_count < len(
            self.info["feedback"]
        ):
            err_msg += "App require {} feedback but only {} are connected".format(
                len(self.info["feedback"]), feedback_count
            )
        if err_msg != "":
            return False, err_msg
        return True, "Now running Hip Extension App"
    #############################################################
    # UPON STARTING THE APP
    # If you have anything that needs to happen before the app starts
    # collecting data, you can uncomment the following lines
    # and add the code in there. This function will be called before the
    # run_in_loop() function below.
    #############################################################
    # def on_start_event(self, start_time):
    #     print("In On Start Event: {start_time}")

    ###########################################################
    # RUN APP IN LOOP
    ###########################################################
    def run_in_loop(self):
        self.vibration_measurement.begin_frame()
        try:
            data = self.my_sage.get_next_data()
            try:
                monitor_node = data[self.NodeNum_vibration_monitor]
            except (TypeError, IndexError, KeyError):
                monitor_node = None
            self.vibration_measurement.update(monitor_node, time.monotonic())
            if not self.sensor_frame_valid(data):
                self.data_valid_state = 0
                self.invalid_frame_count += 1
                self.block_reward_feedback(67)
                self.right_angle_window.clear()
                self.left_angle_window.clear()
                self.selected_trend_window.clear()
                self.previous_filtered_selected_Hip_ext = None
                if not self.hip_calibrated:
                    self.yaw_correction = None
                    self.standing_calibration.reset(4)
                required = ("SensorIndex", "AccelX", "AccelY", "AccelZ", "GyroX", "GyroY",
                            "GyroZ", "MagX", "MagY", "MagZ", "Quat1", "Quat2", "Quat3",
                            "Quat4", "Sampletime", "Package")
                if (isinstance(data, (list, tuple)) and len(data) == len(self.info["sensors"])
                        and all(isinstance(node, dict) and all(key in node for key in required)
                                for node in data)):
                    return self.save_frame(data)
                self.vibration_measurement.mark_recording_gap()
                self.iteration += 1
                return True
            self.data_valid_state = 1
            return self._run_valid_frame(data)
        except Exception:
            self.block_reward_feedback(67)
            raise

    def _run_valid_frame(self, data):

        # YawCorrection mutates its input. Keep raw sensor data intact for
        # existing recording/debug consumers, and correct a separate copy.
        hip_data = [dict(sensor) for sensor in data]
        if not self.hip_calibrated:
            nodes = {
                "pelvis": self.NodeNum_pelvis,
                "right_thigh": self.NodeNum_right_thigh,
                "left_thigh": self.NodeNum_left_thigh,
            }
            poses = {name: get_rotation(data, index).as_quat(scalar_first=True)
                     for name, index in nodes.items()}
            if self.standing_calibration.update(poses, self.iteration, time.monotonic()):
                calibration_data = [dict(sensor) for sensor in data]
                for name, index in nodes.items():
                    mean = self._mean_quat(self.standing_calibration.buffers[name])
                    for field, value in zip(("Quat1", "Quat2", "Quat3", "Quat4"),
                                            mean.as_quat(scalar_first=True)):
                        calibration_data[index][field] = value
                self.yaw_correction = YawCorrection(
                    calibration_data, self.NodeNum_pelvis, self.yaw_offsets,
                    sensor_indices=(self.NodeNum_right_thigh, self.NodeNum_left_thigh,
                                    self.NodeNum_pelvis))
                calibration_data = self.yaw_correction.correct_yaw(calibration_data)
                self.right_joint_angles.calibrate(
                    get_rotation(calibration_data, self.NodeNum_pelvis),
                    get_rotation(calibration_data, self.NodeNum_right_thigh),
                )
                self.left_joint_angles.calibrate(
                    get_rotation(calibration_data, self.NodeNum_pelvis),
                    get_rotation(calibration_data, self.NodeNum_left_thigh),
                )
                self.hip_calibrated = True

        if self.yaw_correction is not None:
            hip_data = self.yaw_correction.correct_yaw(hip_data)
        self.pelvis_quat = get_rotation(hip_data, self.NodeNum_pelvis)
        self.right_thigh_quat = get_rotation(hip_data, self.NodeNum_right_thigh)
        self.left_thigh_quat = get_rotation(hip_data, self.NodeNum_left_thigh)

        if self.hip_calibrated:
            self.right_Hip_ext = self.right_joint_angles.calculate_Hip_Flex(
                self.pelvis_quat, self.right_thigh_quat
            )
            self.left_Hip_ext = self.left_joint_angles.calculate_Hip_Flex(
                self.pelvis_quat, self.left_thigh_quat
            )
            self.right_angle_window.append(self.right_Hip_ext)
            self.left_angle_window.append(self.left_Hip_ext)
            self.filtered_right_Hip_ext = float(np.mean(self.right_angle_window))
            self.filtered_left_Hip_ext = float(np.mean(self.left_angle_window))
            self.update_selected_hip_state()
        self.right_gyro_mag = self.calculate_vector_magnitude(
            data[self.NodeNum_right_thigh], "GyroX", "GyroY", "GyroZ"
        )
        self.left_gyro_mag = self.calculate_vector_magnitude(
            data[self.NodeNum_left_thigh], "GyroX", "GyroY", "GyroZ"
        )
        self.right_acc_mag = self.calculate_vector_magnitude(
            data[self.NodeNum_right_thigh], "AccelX", "AccelY", "AccelZ"
        )
        self.left_acc_mag = self.calculate_vector_magnitude(
            data[self.NodeNum_left_thigh], "AccelX", "AccelY", "AccelZ"
        )
        self.process_training_commands()

        # Give haptic feedback (turn feedback nodes on/off)
        if get_bool(self.config, "feedback_enabled", True) and self.hip_calibrated:
            self.give_feedback()
        else:
            self.block_reward_feedback(68)
            self.min_feedback_state = FEEDBACK_OFF
            self.max_feedback_state = FEEDBACK_OFF
            self.posterior_feedback_state = FEEDBACK_OFF
            self.front_feedback_state = FEEDBACK_OFF
            self.feedback_progress_ratio = 0.0
            self.terminal_goal_met_state = FEEDBACK_OFF

        return self.save_frame(data)

    def save_frame(self, data):
        time_now = self.iteration / self.DATARATE  # nominal sample time; monitor logs its own clocks
        self.emit_orientation_debug(time_now, data)
        self.refresh_vibration_diagnostics()

        my_data = {
            "hip_calibrated_state": [int(self.hip_calibrated)],
            "standing_calibration_state": [self.standing_calibration.state],
            "standing_stable_elapsed_sec": [self.standing_calibration.elapsed],
            "standing_stability_reset_count": [self.standing_calibration.reset_count],
            "standing_stability_deviation_deg": [self.standing_calibration.deviation_deg],
            'time': [time_now],
            "selected_Hip_ext": [self.selected_Hip_ext],
            "filtered_selected_Hip_ext": [self.filtered_selected_Hip_ext],
            "selected_hip_signed_extension_deg": [
                self.selected_hip_signed_extension_deg
            ],
            "selected_hip_forward_side_state": [
                self.selected_hip_forward_side_state
            ],
            "selected_hip_extension_side_state": [
                self.selected_hip_extension_side_state
            ],
            "target_leg_back_state": [self.target_leg_back_state],
            "opposite_leg_forward_state": [self.opposite_leg_forward_state],
            "selected_hip_velocity": [self.selected_hip_velocity],
            "selected_hip_trend": [self.selected_hip_trend],
            "selected_hip_extending_state": [self.selected_hip_extending_state],
            "selected_hip_flexing_state": [self.selected_hip_flexing_state],
            "calibration_state": [self.calibration_controller.state],
            "calibration_sample_count": [self.calibration_controller.sample_count],
            "calibration_step_count": [self.calibration_controller.step_count],
            "calibration_target_phase_sec": [
                self.calibration_controller.target_phase_sec
            ],
            "calibration_suggested_threshold": [
                self.value_or_zero(self.calibration_controller.suggested_threshold)
            ],
            "calibration_confirmed_threshold": [
                self.value_or_zero(self.calibration_controller.confirmed_threshold)
            ],
            "adaptive_current_threshold": [
                self.adaptive_threshold_controller.current_threshold
            ],
            "adaptive_stage": [self.adaptive_threshold_controller.stage],
            "adaptive_eval_elapsed_sec": [
                self.adaptive_threshold_controller.eval_elapsed_sec
            ],
            "adaptive_eval_target_phase_sec": [
                float(self.adaptive_threshold_controller.eval_target_phase_sec)
            ],
            "adaptive_success_ratio": [
                self.adaptive_threshold_controller.success_ratio
            ],
            "adaptive_adjust_count": [
                self.adaptive_threshold_controller.adjust_count
            ],
            "adaptive_reason_code": [
                self.adaptive_threshold_controller.reason_code
            ],
            "adaptive_mode_state": [self.adaptive_mode_state],
            "adaptive_assessed_threshold": [self.adaptive_assessed_threshold],
            "adaptive_assessment_elapsed_sec": [
                self.adaptive_assessment_elapsed_sec
            ],
            "adaptive_assessment_sample_count": [
                self.adaptive_assessment_sample_count
            ],
            "adaptive_assessment_extension_sample_count": [
                self.adaptive_assessment_extension_sample_count
            ],
            "adaptive_current_level": [self.adaptive_current_level],
            "adaptive_level_up_event_state": [self.adaptive_level_up_event_state],
            "adaptive_window_success_samples": [
                self.adaptive_window_success_samples
            ],
            "adaptive_window_valid_samples": [
                self.adaptive_window_valid_samples
            ],
            "adaptive_last_window_success_samples": [
                self.adaptive_last_window_success_samples
            ],
            "adaptive_last_window_valid_samples": [
                self.adaptive_last_window_valid_samples
            ],
            "adaptive_latest_step_peak_deg": [self.adaptive_latest_step_peak_deg],
            "adaptive_current_step_peak_deg": [self.adaptive_current_step_peak_deg],
            "adaptive_last_step_peak_deg": [self.adaptive_last_step_peak_deg],
            "adaptive_last_step_success_state": [
                self.adaptive_last_step_success_state
            ],
            "adaptive_last_step_valid_state": [
                self.adaptive_last_step_valid_state
            ],
            "adaptive_last_step_reject_reason": [
                self.adaptive_last_step_reject_reason
            ],
            "min_feedback_state": [self.min_feedback_state],
            "feedback_progress_ratio": [self.feedback_progress_ratio],
            "feedback_interval_ms": [self.feedback_interval_ms],
            "vibration_total_count": [self.vibration_total_count],
            "vibration_recent_count_60s": [self.vibration_recent_count_60s],
            "vibration_rate_per_min_60s": [self.vibration_rate_per_min_60s],
            "vibration_last_duration_sec": [self.vibration_last_duration_sec],
            "vibration_last_strength": [self.vibration_last_strength],
            "terminal_goal_met_state": [self.terminal_goal_met_state],
            "gait_cycle_index": [self.gait_cycle_index],
            "gait_phase_state": [self.gait_phase_state],
            "stance_phase_state": [self.stance_phase_state],
            "swing_phase_state": [self.swing_phase_state],
            "heel_strike_event_state": [self.heel_strike_event_state],
            "mid_stance_event_state": [self.mid_stance_event_state],
            "toe_off_event_state": [self.toe_off_event_state],
            "swing_deceleration_state": [self.swing_deceleration_state],
            "current_cycle_peak_extension": [self.current_cycle_peak_extension],
            "previous_cycle_peak_extension": [self.previous_cycle_peak_extension],
            "previous_cycle_feedback_level": [self.previous_cycle_feedback_level],
            "current_feedback_level": [self.current_feedback_level],
            "posterior_feedback_state": [self.posterior_feedback_state],
            "front_feedback_state": [self.front_feedback_state],
            "angle_feedback_level": [self.angle_feedback_level],
            "angle_limit_burst_count": [self.angle_limit_burst_count],
            "angle_limit_burst_remaining": [self.angle_limit_burst_remaining],
            "angle_limit_latched_state": [self.angle_limit_latched_state],
            "deficit_feedback_deficit_deg": [self.deficit_feedback_deficit_deg],
            "deficit_feedback_machine_state": [self.deficit_feedback_machine_state],
            "deficit_feedback_armed_state": [self.deficit_feedback_armed_state],
            "deficit_feedback_success_latched_state": [
                self.deficit_feedback_success_latched_state
            ],
            "deficit_feedback_target_dwell_state": [
                self.deficit_feedback_target_dwell_state
            ],
            "deficit_feedback_reset_dwell_state": [
                self.deficit_feedback_reset_dwell_state
            ],
            "right_Hip_ext": [self.right_Hip_ext],
            "left_Hip_ext": [self.left_Hip_ext],
            "filtered_right_Hip_ext": [self.filtered_right_Hip_ext],
            "filtered_left_Hip_ext": [self.filtered_left_Hip_ext],
            "right_leg_back_state": [self.right_leg_back_state],
            "left_leg_forward_state": [self.left_leg_forward_state],
            "target_phase_state": [self.target_phase_state],
            "right_hip_velocity": [self.right_hip_velocity],
            "right_hip_trend": [self.right_hip_trend],
            "right_hip_extending_state": [self.right_hip_extending_state],
            "right_hip_flexing_state": [self.right_hip_flexing_state],
            "feedback_phase_state": [self.feedback_phase_state],
            "feedback_metric": [self.feedback_metric],
            "feedback_reason_code": [self.feedback_reason_code],
            "right_gyro_mag": [self.right_gyro_mag],
            "left_gyro_mag": [self.left_gyro_mag],
            "right_acc_mag": [self.right_acc_mag],
            "left_acc_mag": [self.left_acc_mag],
            "debug_orientation_udp_send_count": [self.debug_orientation_udp_send_count],
            "debug_orientation_udp_error_count": [self.debug_orientation_udp_error_count],
            "debug_orientation_udp_last_error_code": [self.debug_orientation_udp_last_error_code],
            "training_command_received_count": [self.training_command_received_count],
            "target_met": [int(self.threshold_met_state)],
        }

        my_data.update(self.reward_metrics())
        omitted_vibration_settings = {
            "vibration_measurement_schema_version",
            "vibration_detection_configured",
            "vibration_command_strength",
            "vibration_threshold_mps2",
            "vibration_highpass_hz",
            "vibration_rms_window_ms",
            "vibration_match_tolerance_sec",
            "vibration_on_dwell_ms",
            "vibration_off_dwell_ms",
        }
        my_data.update({
            name: [value]
            for name, value in self.vibration_measurement.metrics().items()
            if name not in omitted_vibration_settings
        })
        self.my_sage.save_data(data, my_data)
        self.my_sage.send_stream_data(data, my_data)

        self.iteration += 1
        return True
    #############################################################
    # MANAGE FEEDBACK FOR APP
    #############################################################
    def stop_feedback(self, feedbackNode=None, force=False):
        if self.vibration_output_requested is False and not force:
            return
        node = self.NodeNum_vibration_monitor if feedbackNode is None else feedbackNode
        started = time.monotonic()
        try:
            self.my_sage.sensor_vibration_off(node)
        except Exception:
            self.vibration_measurement.command_error()
            raise
        self.vibration_measurement.command_off(started, time.monotonic())
        self.vibration_output_requested = False

    def trigger_vibration(self, feedbackNode, duration, strength):
        duration = min(float(duration), MAX_REWARD_PULSE_DURATION_SEC)
        strength = validate_vibration_strength(strength)
        if strength != self.feedback_strength:
            raise ValueError("All rewards must use the configured feedback strength")
        started = time.monotonic()
        try:
            self.my_sage.sensor_vibration_on(
                feedbackNode, duration=duration, strength=strength)
        except Exception:
            self.vibration_measurement.command_error()
            raise
        self.vibration_measurement.command_on(started, time.monotonic(), duration, strength)
        self.vibration_output_requested = True
        self.record_vibration_event(duration, strength)

    def record_vibration_event(self, duration, strength):
        self.vibration_total_count += 1
        self.vibration_last_duration_sec = float(duration)
        self.vibration_last_strength = int(strength)
        self.vibration_event_iters.append(int(self.iteration))
        self.refresh_vibration_diagnostics()

    def refresh_vibration_diagnostics(self):
        window_samples = max(
            1, int(round(float(self.vibration_recent_window_sec) * self.DATARATE))
        )
        min_iter = int(self.iteration) - window_samples
        while self.vibration_event_iters and self.vibration_event_iters[0] < min_iter:
            self.vibration_event_iters.popleft()
        self.vibration_recent_count_60s = len(self.vibration_event_iters)
        self.vibration_rate_per_min_60s = (
            self.vibration_recent_count_60s * 60.0 / self.vibration_recent_window_sec
        )
        self.vibration_interval_ms_state = float(self.feedback_interval_ms)
        if self.vibration_interval_ms_state > 0:
            self.vibration_frequency_hz_state = 1000.0 / self.vibration_interval_ms_state
        else:
            self.vibration_frequency_hz_state = 0.0

    def calculate_vector_magnitude(self, node_data, x_key, y_key, z_key):
        x = float(node_data[x_key])
        y = float(node_data[y_key])
        z = float(node_data[z_key])
        return float(np.sqrt(x * x + y * y + z * z))

    def get_node_quaternion(self, data, node_num):
        return [
            data[node_num]["Quat1"],
            data[node_num]["Quat2"],
            data[node_num]["Quat3"],
            data[node_num]["Quat4"],
        ]

    def get_udp_host_last_octet(self, host):
        try:
            return int(str(host).strip().split(".")[-1])
        except (TypeError, ValueError):
            return -1

    def value_or_zero(self, value):
        if value is None:
            return 0.0
        return value

    def process_training_commands(self):
        if not self.training_command_socket:
            return
        # Keep control processing bounded so a busy UDP socket cannot starve
        # motor-off timers and sensor processing.
        for _ in range(16):
            try:
                packet, _addr = self.training_command_socket.recvfrom(2048)
            except BlockingIOError:
                return
            except OSError as exc:
                self.training_command_last_error_code = int(exc.errno or -1)
                return
            try:
                payload = json.loads(packet.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(payload, dict) and payload.get("command") == "confirm_calibration":
                if self.confirm_calibration(payload.get("threshold")) is not None:
                    self.training_command_received_count += 1

    def confirm_calibration(self, threshold=None):
        if threshold is None:
            threshold = self.calibration_controller.suggested_threshold
        try:
            value = float(threshold)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(value) or value <= 0:
            return None
        confirmed = self.calibration_controller.confirm(value)
        if confirmed is None or confirmed <= 0:
            return None
        self.block_reward_feedback(50)
        self.min_threshold = confirmed
        self.initial_min_threshold = confirmed
        self.adaptive_threshold_controller.reset(confirmed)
        self.sync_adaptive_display_state()
        return confirmed

    def emit_orientation_debug(self, time_now, data):
        if not self.debug_orientation_enabled:
            return
        if not should_emit_debug(
            self.iteration, self.DATARATE, self.debug_orientation_hz
        ):
            return

        payload = build_orientation_payload(
            sample_index=self.iteration,
            time_sec=time_now,
            node_quaternions={
                "pelvis": self.get_node_quaternion(data, self.NodeNum_pelvis),
                "right_thigh": self.get_node_quaternion(
                    data, self.NodeNum_right_thigh
                ),
                "left_thigh": self.get_node_quaternion(data, self.NodeNum_left_thigh),
            },
            hip_metrics={
                "right_Hip_ext": self.right_Hip_ext,
                "left_Hip_ext": self.left_Hip_ext,
                "filtered_right_Hip_ext": self.filtered_right_Hip_ext,
                "filtered_left_Hip_ext": self.filtered_left_Hip_ext,
                "training_leg_state": self.training_leg_state,
                "selected_Hip_ext": self.selected_Hip_ext,
                "filtered_selected_Hip_ext": self.filtered_selected_Hip_ext,
                "target_phase_state": self.target_phase_state,
                "feedback_phase_state": self.feedback_phase_state,
                "min_feedback_state": self.min_feedback_state,
                "feedback_reason_code": self.feedback_reason_code,
                "feedback_progress_ratio": self.feedback_progress_ratio,
                "feedback_interval_ms": self.feedback_interval_ms,
                "terminal_goal_met_state": self.terminal_goal_met_state,
                "gait_phase_state": self.gait_phase_state,
                "stance_phase_state": self.stance_phase_state,
                "swing_phase_state": self.swing_phase_state,
                "current_feedback_level": self.current_feedback_level,
                "posterior_feedback_state": self.posterior_feedback_state,
                "front_feedback_state": self.front_feedback_state,
                "angle_feedback_level": self.angle_feedback_level,
                "angle_limit_burst_remaining": self.angle_limit_burst_remaining,
            },
        )

        if self.debug_orientation_print_enabled:
            print(format_orientation_summary(payload))

        if self.debug_orientation_udp_enabled and self.debug_orientation_socket:
            try:
                self.debug_orientation_socket.sendto(
                    encode_orientation_packet(payload),
                    (
                        self.debug_orientation_udp_host,
                        self.debug_orientation_udp_port,
                    ),
                )
                self.debug_orientation_udp_send_count += 1
                self.debug_orientation_udp_last_error_code = 0
            except OSError as exc:
                self.debug_orientation_udp_error_count += 1
                self.debug_orientation_udp_last_error_code = int(exc.errno or -1)

    def get_feedback_metric(self):
        if self.feedback_mode == "gyro_mag":
            self.feedback_mode_code = 1
            if self.training_leg == "left":
                return self.left_gyro_mag
            return self.right_gyro_mag
        if self.feedback_mode == "acc_mag":
            self.feedback_mode_code = 2
            if self.training_leg == "left":
                return self.left_acc_mag
            return self.right_acc_mag
        self.feedback_mode_code = 0
        return self.filtered_selected_Hip_ext

    def get_training_extension_metric(self):
        if self.extension_direction == "decreasing":
            return -float(self.filtered_selected_Hip_ext)
        return float(self.filtered_selected_Hip_ext)

    def get_training_extension_metric_from_raw_angle(self, raw_angle):
        if self.extension_direction == "decreasing":
            return -float(raw_angle)
        return float(raw_angle)

    def is_forward_side_raw_angle(self, raw_angle):
        if self.extension_direction == "decreasing":
            return float(raw_angle) >= 0.0
        return float(raw_angle) <= 0.0

    def below_min_with_hysteresis(self, metric):
        if self.min_feedback_state:
            return metric < self.min_threshold + self.hysteresis_deg
        return metric < self.min_threshold

    def above_min_with_hysteresis(self, metric):
        if self.min_feedback_state:
            return metric > self.min_threshold - self.hysteresis_deg
        return metric > self.min_threshold

    def above_max_with_hysteresis(self, metric):
        if self.max_feedback_state:
            return metric > self.max_threshold - self.hysteresis_deg
        return metric > self.max_threshold

    def compare_with_hysteresis(self, metric, threshold, direction, active_state):
        if direction == "below":
            if active_state:
                return metric < threshold + self.hysteresis_deg
            return metric < threshold
        if active_state:
            return metric > threshold - self.hysteresis_deg
        return metric > threshold

    def update_selected_hip_state(self):
        if self.training_leg == "left":
            self.selected_Hip_ext = self.left_Hip_ext
            self.filtered_selected_Hip_ext = self.filtered_left_Hip_ext
        else:
            self.selected_Hip_ext = self.right_Hip_ext
            self.filtered_selected_Hip_ext = self.filtered_right_Hip_ext

        self.selected_hip_signed_extension_deg = self.get_training_extension_metric()
        self.selected_hip_forward_side_state = int(
            self.is_forward_side_raw_angle(self.filtered_selected_Hip_ext)
        )
        self.selected_hip_extension_side_state = int(
            not self.selected_hip_forward_side_state
        )

        if self.previous_filtered_selected_Hip_ext is None:
            self.selected_hip_velocity = 0.0
        else:
            self.selected_hip_velocity = (
                self.filtered_selected_Hip_ext - self.previous_filtered_selected_Hip_ext
            )
        self.previous_filtered_selected_Hip_ext = self.filtered_selected_Hip_ext

        self.selected_trend_window.append(self.filtered_selected_Hip_ext)
        if len(self.selected_trend_window) > 1:
            self.selected_hip_trend = (
                self.filtered_selected_Hip_ext - self.selected_trend_window[0]
            )
        else:
            self.selected_hip_trend = 0.0

        if self.extension_direction == "increasing":
            is_extending = (
                self.selected_hip_velocity > self.extension_velocity_threshold
                or self.selected_hip_trend > self.extension_trend_threshold
            )
            is_flexing = (
                self.selected_hip_velocity < -self.reset_velocity_threshold
                or self.selected_hip_trend < -self.reset_trend_threshold
            )
        else:
            is_extending = (
                self.selected_hip_velocity < -self.extension_velocity_threshold
                or self.selected_hip_trend < -self.extension_trend_threshold
            )
            is_flexing = (
                self.selected_hip_velocity > self.reset_velocity_threshold
                or self.selected_hip_trend > self.reset_trend_threshold
            )

        self.selected_hip_extending_state = int(is_extending)
        self.selected_hip_flexing_state = int(is_flexing)
        if self.training_leg == "right":
            self.right_hip_velocity = self.selected_hip_velocity
            self.right_hip_trend = self.selected_hip_trend
            self.right_hip_extending_state = self.selected_hip_extending_state
            self.right_hip_flexing_state = self.selected_hip_flexing_state
        else:
            self.right_hip_velocity = 0.0
            self.right_hip_trend = 0.0
            self.right_hip_extending_state = FEEDBACK_OFF
            self.right_hip_flexing_state = FEEDBACK_OFF

    def update_target_phase(self):
        self.right_leg_back_state = int(
            self.compare_with_hysteresis(
                self.filtered_right_Hip_ext,
                self.right_phase_threshold,
                self.right_phase_direction,
                self.right_leg_back_state,
            )
        )
        self.left_leg_forward_state = int(
            self.compare_with_hysteresis(
                self.filtered_left_Hip_ext,
                self.left_forward_threshold,
                self.left_forward_direction,
                self.left_leg_forward_state,
            )
        )
        self.left_leg_back_state = int(
            self.compare_with_hysteresis(
                self.filtered_left_Hip_ext,
                self.left_back_threshold,
                self.left_back_direction,
                self.left_leg_back_state,
            )
        )
        self.right_leg_forward_state = int(
            self.compare_with_hysteresis(
                self.filtered_right_Hip_ext,
                self.right_forward_threshold,
                self.right_forward_direction,
                self.right_leg_forward_state,
            )
        )
        movement_ok = True
        if self.movement_gate_enabled:
            gyro_mag = self.right_gyro_mag if self.training_leg == "right" else self.left_gyro_mag
            movement_ok = gyro_mag >= self.movement_gate_gyro_threshold
        if self.training_leg == "left":
            self.target_leg_back_state = self.left_leg_back_state
            self.opposite_leg_forward_state = self.right_leg_forward_state
        else:
            self.target_leg_back_state = self.right_leg_back_state
            self.opposite_leg_forward_state = self.left_leg_forward_state
        self.target_phase_state = int(
            self.target_leg_back_state
            and self.opposite_leg_forward_state
            and movement_ok
        )

    def update_adaptive_threshold(self):
        event = self.update_extension_peak_tracker()
        if event is not None and event.valid_state:
            success = int(event.peak_deg >= self.min_threshold)
            self.peak_target_met_event = success
            self.min_threshold, _ = self.adaptive_threshold_controller.update_training_step(
                valid_step_state=1, success_state=success, peak_deg=event.peak_deg)
            self.adaptive_last_step_success_state = success
        self.min_threshold, adjusted = self.adaptive_threshold_controller.update_time_sample(
            allow_evaluation=not self.extension_peak_tracker.in_episode)
        self.sync_adaptive_display_state()
        return adjusted

    def update_adaptive_assessment(self):
        self.adaptive_level_up_event_state = FEEDBACK_OFF
        event = self.update_extension_peak_tracker()
        if event is not None and event.valid_state:
            self.min_threshold, _step_adjusted = (
                self.adaptive_threshold_controller.update_assessment_step(
                    valid_step_state=1,
                    peak_deg=event.peak_deg,
                )
            )
            self.adaptive_last_step_success_state = FEEDBACK_OFF
            self.adaptive_last_step_valid_state = FEEDBACK_ON
        self.min_threshold, _adjusted = self.adaptive_threshold_controller.update_time_sample()
        self.sync_adaptive_display_state()
        self.apply_training_threshold_to_feedback_strategy()

    def update_extension_peak_tracker(self):
        tracker = self.extension_peak_tracker
        event = tracker.update(self.selected_hip_signed_extension_deg, self.iteration,
                               self.selected_hip_extension_side_state)
        self.adaptive_current_step_peak_deg = float(tracker.current_peak_deg)
        peak = tracker.local_peak_event
        self.local_peak_event_state = int(peak is not None)
        if peak is not None:
            self.local_peak_latest_deg = peak.peak_deg
            self.local_peak_sample = peak.peak_sample
            self.local_peak_confirmed_sample = peak.confirmed_sample
        if event is not None:
            self.adaptive_last_step_peak_deg = event.peak_deg
            self.adaptive_latest_step_peak_deg = event.peak_deg
            self.adaptive_last_step_valid_state = event.valid_state
            self.adaptive_last_step_success_state = 0
            self.adaptive_last_step_reject_reason = event.reject_reason
            self.last_episode_candidate_count = event.candidate_count
        return event

    def adaptive_assessment_blocks_training(self):
        if not self.adaptive_threshold_controller.enabled:
            return False
        if self.adaptive_threshold_controller.mode != ADAPTIVE_MODE_ASSESSMENT:
            return False
        self.update_adaptive_assessment()
        self.feedback_phase_state = PHASE_WAITING
        self.feedback_reason_code = 50
        self.angle_feedback_level = ANGLE_LEVEL_UNKNOWN
        self.deficit_feedback_deficit_deg = 0.0
        self.min_feedback_state = FEEDBACK_OFF
        self.posterior_feedback_state = FEEDBACK_OFF
        self.front_feedback_state = FEEDBACK_OFF
        self.max_feedback_state = FEEDBACK_OFF
        self.toggle_all_feedback_off()
        return True


    def apply_training_threshold_to_feedback_strategy(self):
        if not (self.deficit_feedback_enabled and self.feedback_mode == "angle"):
            return
        self.deficit_feedback_strategy.reset_margin_deg = min(
            self.default_deficit_reset_margin_deg,
            max(0.0, float(self.min_threshold) - 0.5),
        )

    def update_deficit_forward_rearm(self, forward_side_frame):
        if (
            not forward_side_frame
            or self.deficit_feedback_strategy.machine_state
            != DEFICIT_STATE_SUCCESS_LATCHED
        ):
            self.deficit_forward_rearm_started_iter = None
            return
        if self.deficit_forward_rearm_started_iter is None:
            self.deficit_forward_rearm_started_iter = int(self.iteration)
            return
        if (
            int(self.iteration) - int(self.deficit_forward_rearm_started_iter)
            >= self.deficit_feedback_strategy.reset_dwell_samples
        ):
            self.deficit_feedback_strategy.rearm_after_external_reset()
            self.deficit_forward_rearm_started_iter = None

    def sync_adaptive_display_state(self):
        controller = self.adaptive_threshold_controller
        self.adaptive_mode_state = int(getattr(controller, "mode", ADAPTIVE_MODE_DISABLED))
        self.adaptive_assessed_threshold = float(
            getattr(controller, "assessed_threshold", 0.0)
        )
        self.adaptive_assessment_elapsed_sec = float(
            getattr(controller, "assessment_elapsed_sec", 0.0)
        )
        self.adaptive_assessment_sample_count = int(
            getattr(controller, "assessment_sample_count", 0)
        )
        self.adaptive_assessment_extension_sample_count = int(
            getattr(controller, "assessment_extension_sample_count", 0)
        )
        self.adaptive_current_level = int(
            getattr(controller, "current_level", controller.stage + 1)
        )
        self.adaptive_step_deg_state = float(getattr(controller, "step_deg", 1.0))
        self.adaptive_success_ratio_percent = float(
            getattr(controller, "success_ratio_percent", controller.success_ratio * 100.0)
        )
        self.adaptive_window_success_samples = int(
            getattr(controller, "window_success_samples", 0)
        )
        self.adaptive_window_valid_samples = int(
            getattr(controller, "window_valid_samples", 0)
        )
        self.adaptive_last_window_success_samples = int(
            getattr(controller, "last_window_success_samples", 0)
        )
        self.adaptive_last_window_valid_samples = int(
            getattr(controller, "last_window_valid_samples", 0)
        )
        self.adaptive_latest_step_peak_deg = float(
            getattr(controller, "latest_step_peak_deg", self.adaptive_latest_step_peak_deg)
        )
        self.adaptive_last_step_success_state = int(
            getattr(controller, "last_step_success_state", self.adaptive_last_step_success_state)
        )
        self.adaptive_min_valid_steps_per_window_state = int(
            getattr(controller, "min_target_phase_samples", 0)
        )

    def update_threshold_met_state(self):
        if self.threshold_target_direction == "decreasing":
            if self.threshold_met_state:
                threshold_met = self.feedback_metric <= (
                    self.min_threshold + self.hysteresis_deg
                )
            else:
                threshold_met = self.feedback_metric <= self.min_threshold
        else:
            if self.threshold_met_state:
                threshold_met = self.feedback_metric >= (
                    self.min_threshold - self.hysteresis_deg
                )
            else:
                threshold_met = self.feedback_metric >= self.min_threshold
        self.threshold_met_state = int(threshold_met)
        return self.threshold_met_state

    def reset_feedback_outputs(self):
        self.toggle_all_feedback_off()
        self.min_feedback_state = FEEDBACK_OFF
        self.max_feedback_state = FEEDBACK_OFF
        self.posterior_feedback_state = FEEDBACK_OFF
        self.front_feedback_state = FEEDBACK_OFF
        self.feedback_progress_ratio = 0.0
        self.feedback_interval_ms = float(self.vibration_controller.min_interval_ms)
        self.terminal_goal_met_state = FEEDBACK_OFF
        self.threshold_met_state = FEEDBACK_OFF
        self.active_min_feedback_until_iter = None
        self.active_front_feedback_until_iter = None
        self.vibration_controller.reset()
        self.deficit_feedback_strategy.reset()
        self.previous_feedback_raw_hip_ext = None
        self.last_deficit_feedback_decision = None
        self.last_forward_level1_feedback_iter = None
        self.deficit_feedback_machine_state = DEFICIT_STATE_DISARMED
        self.deficit_feedback_armed_state = FEEDBACK_OFF
        self.deficit_feedback_success_latched_state = FEEDBACK_OFF
        self.deficit_feedback_target_dwell_state = FEEDBACK_OFF
        self.deficit_feedback_reset_dwell_state = FEEDBACK_OFF

    def update_min_feedback_off_timer(self):
        if self.active_min_feedback_until_iter is None:
            return
        if self.iteration >= self.active_min_feedback_until_iter:
            self.stop_feedback(self.NodeNum_vibration_monitor)
            self.active_min_feedback_until_iter = None
            self.posterior_feedback_state = FEEDBACK_OFF

    def update_front_feedback_off_timer(self):
        if self.active_front_feedback_until_iter is None:
            return
        if self.iteration >= self.active_front_feedback_until_iter:
            if self.NodeNum_feedback_front is not None:
                self.stop_feedback(self.NodeNum_feedback_front)
            self.active_front_feedback_until_iter = None
            self.front_feedback_state = FEEDBACK_OFF

    def _forward_level1_due(self):
        if self.last_forward_level1_feedback_iter is None:
            return True
        interval_samples = max(
            1,
            int(
                round(
                    float(self.deficit_feedback_strategy.level1_interval_ms)
                    * self.DATARATE
                    / 1000.0
                )
            ),
        )
        return self.iteration - self.last_forward_level1_feedback_iter >= interval_samples

    def calibration_blocks_training(self):
        if not self.calibration_controller.enabled:
            return False
        if self.calibration_controller.state == CALIBRATION_CONFIRMED:
            return False
        if self.calibration_controller.state == CALIBRATION_COLLECTING:
            self.calibration_controller.update(
                self.feedback_metric,
                target_phase_state=self.target_phase_state,
            )
        if self.calibration_controller.state == CALIBRATION_READY:
            self.feedback_reason_code = 8
        else:
            self.feedback_reason_code = 7
        self.feedback_phase_state = PHASE_WAITING
        self.reset_feedback_outputs()
        return True


    def give_feedback(self):
        self.reward_qualified_event = 0
        self.reward_sent_event = 0
        self.reward_suppressed_event = 0
        self.peak_target_met_event = 0
        self.adaptive_level_up_event_state = 0
        self.update_target_phase()
        self.feedback_metric = self.get_training_extension_metric()
        if self.calibration_blocks_training():
            self.block_reward_feedback(7)
            return
        if self.adaptive_assessment_blocks_training():
            self.block_reward_feedback(50, reset_tracker=False)
            if self.adaptive_threshold_controller.mode != ADAPTIVE_MODE_ASSESSMENT:
                self.extension_peak_tracker.reset()
            return
        self.update_adaptive_threshold()
        decision = self.reward_controller.update(
            self.get_training_extension_metric(), self.min_threshold,
            self.iteration)
        if decision.stop:
            self.stop_feedback(self.NodeNum_vibration_monitor)
        if decision.pulse_kind:
            self.trigger_vibration(self.NodeNum_vibration_monitor,
                                   decision.duration, decision.strength)
        rc = self.reward_controller
        self.reward_qualified_event = int(decision.qualified)
        self.reward_sent_event = int(decision.pulse_kind == PULSE_REWARD)
        self.reward_suppressed_event = int(decision.suppressed)
        self.adaptive_level_up_event_state = 0  # Legacy upgrade-vibration event.
        self.min_feedback_state = int(bool(rc.active_kind))
        self.posterior_feedback_state = self.min_feedback_state
        self.front_feedback_state = self.max_feedback_state = FEEDBACK_OFF
        self.feedback_interval_ms = 0.0
        target = rc.cycle_target if rc.in_cycle else self.min_threshold
        self.threshold_met_state = int(self.feedback_metric >= target)
        self.terminal_goal_met_state = int(rc.cycle_qualified)
        self.feedback_progress_ratio = max(0.0, min(1.0, self.feedback_metric / target))
        self.angle_feedback_level = 3 if rc.cycle_qualified else 0
        self.feedback_phase_state = PHASE_QUALIFIED if rc.cycle_qualified else (
            PHASE_EXTENDING if rc.in_cycle else PHASE_WAITING)
        self.feedback_reason_code = (66 if decision.suppressed else
            63 if decision.pulse_kind == PULSE_REWARD else
            64 if rc.cycle_qualified else 62 if rc.target_since is not None else
            61 if rc.in_cycle or rc.armed else 60)

    def update_gait_phase_state(self):
        state = self.gait_controller.update(
            angle=self.filtered_selected_Hip_ext,
            sample_index=self.iteration,
            target_leg_back_state=self.target_leg_back_state,
            opposite_leg_forward_state=self.opposite_leg_forward_state,
            selected_hip_extending_state=self.selected_hip_extending_state,
            selected_hip_flexing_state=self.selected_hip_flexing_state,
        )
        self.gait_cycle_index = state.gait_cycle_index
        self.gait_phase_state = state.gait_phase_state
        self.stance_phase_state = state.stance_phase_state
        self.swing_phase_state = state.swing_phase_state
        self.heel_strike_event_state = state.heel_strike_event_state
        self.mid_stance_event_state = state.mid_stance_event_state
        self.toe_off_event_state = state.toe_off_event_state
        self.swing_deceleration_state = state.swing_deceleration_state
        self.current_cycle_peak_extension = state.current_cycle_peak_extension
        self.previous_cycle_peak_extension = state.previous_cycle_peak_extension
        self.previous_cycle_feedback_level = state.previous_cycle_feedback_level
        self.current_feedback_level = state.current_feedback_level



    def toggle_all_feedback_off(self):
        self.stop_feedback(self.NodeNum_vibration_monitor)

    #############################################################
    # UPON STOPPING THE APP
    # If you have anything that needs to happen after the app stops,
    # you can uncomment the following lines and add the code in there.
    # This function will be called after the data file is saved and
    # can be read back in for reporting purposes if needed.
    #############################################################
    # def on_stop_event(self, stop_time):
    #     print(f"In On Stop Event: {stop_time}")

    def sensor_frame_valid(self, data):
        try:
            for index in (self.NodeNum_right_thigh, self.NodeNum_left_thigh, self.NodeNum_pelvis):
                node = data[index]
                q = [float(node["Quat{}".format(i)]) for i in range(1, 5)]
                other = [float(node[k]) for k in
                         ("GyroX", "GyroY", "GyroZ", "AccelX", "AccelY", "AccelZ")]
                if not np.all(np.isfinite(q + other)) or np.linalg.norm(q) < 1e-12:
                    return False
        except (TypeError, ValueError, KeyError, IndexError):
            return False
        return True

    def block_reward_feedback(self, reason, reset_tracker=True):
        self.reward_controller.reset()
        self.toggle_all_feedback_off()
        self.active_min_feedback_until_iter = None
        self.active_front_feedback_until_iter = None
        self.min_feedback_state = self.posterior_feedback_state = 0
        self.front_feedback_state = self.max_feedback_state = 0
        self.reward_qualified_event = self.reward_sent_event = self.reward_suppressed_event = 0
        self.adaptive_level_up_event_state = 0
        self.threshold_met_state = self.terminal_goal_met_state = 0
        self.angle_feedback_level = 0
        self.feedback_phase_state = PHASE_WAITING
        self.feedback_reason_code = reason
        self.feedback_interval_ms = self.feedback_progress_ratio = 0.0
        self.peak_target_met_event = 0
        if reset_tracker:
            self.extension_peak_tracker.reset()
            self.local_peak_event_state = 0
            self.adaptive_current_step_peak_deg = 0.0

    def reward_metrics(self):
        rc = self.reward_controller
        values = {
            "reward_armed_state": int(rc.armed or rc.in_cycle),
            "reward_cycle_index": rc.cycle_index,
            "reward_cycle_target_deg": rc.cycle_target,
            "reward_cycle_qualified_state": int(rc.cycle_qualified),
            "reward_qualified_event": self.reward_qualified_event,
            "reward_sent_event": self.reward_sent_event,
            "reward_suppressed_event": self.reward_suppressed_event,
            "reward_qualified_count": rc.qualified_count,
            "reward_sent_count": rc.reward_count,
            "reward_suppressed_count": rc.suppressed_count,
            "reward_upgrade_count": rc.level_up_count,
            "reward_active_kind": rc.active_kind,
            "reward_upgrade_pending_state": int(rc.pending_level_up),
            "local_peak_event_state": self.local_peak_event_state,
            "local_peak_latest_deg": self.local_peak_latest_deg,
            "local_peak_sample": self.local_peak_sample,
            "local_peak_confirmed_sample": self.local_peak_confirmed_sample,
            "last_episode_candidate_count": self.last_episode_candidate_count,
            "peak_target_met_event": self.peak_target_met_event,
            "data_valid_state": self.data_valid_state,
            "invalid_frame_count": self.invalid_frame_count,
        }
        return {name: [value] for name, value in values.items()}

    def on_stop_event(self, stop_time):
        try:
            self.stop_feedback(force=True)
            self.block_reward_feedback(68)
        finally:
            for name in ("training_command_socket", "debug_orientation_socket"):
                sock = getattr(self, name, None)
                if sock is not None:
                    sock.close()
                    setattr(self, name, None)
