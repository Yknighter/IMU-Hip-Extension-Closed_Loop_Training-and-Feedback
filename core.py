import time
import socket
import numpy as np
from collections import deque
from sage.base_app import BaseApp
from .Rotation import Rotation as R
from .JointAngles import JointAngles
from .orientation_debug import (
    build_orientation_payload,
    encode_orientation_packet,
    format_orientation_summary,
    should_emit_debug,
)

FEEDBACK_OFF = 0
FEEDBACK_ON = 1
PHASE_WAITING = 0
PHASE_EXTENDING = 1
PHASE_QUALIFIED = 2

def get_bool(config, key, default=False):
    value = config.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)

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

        self.DATARATE = self.info["datarate"]
        self.pulse_length = self.info["pulse_length"]
        self.min_threshold = float(self.config["min_threshold"])
        self.max_threshold = float(self.config.get("max_threshold", 20.0))
        self.feedback_mode = self.config.get("feedback_mode", "angle")
        self.feedback_trigger_direction = self.config.get(
            "feedback_trigger_direction", "above"
        )
        self.phase_gate_enabled = get_bool(self.config, "phase_gate_enabled", True)
        self.right_phase_threshold = float(self.config.get("right_phase_threshold", -90.0))
        self.right_phase_direction = self.config.get("right_phase_direction", "above")
        self.left_forward_threshold = float(self.config.get("left_forward_threshold", 0.0))
        self.left_forward_direction = self.config.get("left_forward_direction", "above")
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
        self.NodeNum_feedback_min = self.info["feedback"].index('feedback_min')
        self.NodeNum_feedback_max = (
            self.info["feedback"].index("feedback_max")
            if "feedback_max" in self.info["feedback"]
            else None
        )

        self.iteration = 0
        self.right_joint_angles = JointAngles(True)
        self.left_joint_angles = JointAngles(False)
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
        self.left_leg_forward_state = FEEDBACK_OFF
        self.target_phase_state = FEEDBACK_OFF
        self.right_hip_velocity = 0.0
        self.right_hip_trend = 0.0
        self.right_hip_extending_state = FEEDBACK_OFF
        self.right_hip_flexing_state = FEEDBACK_OFF
        self.feedback_phase_state = PHASE_WAITING
        self.previous_filtered_right_Hip_ext = None

        self.right_thigh_quat = None
        self.left_thigh_quat = None
        self.right_angle_window = deque(maxlen=self.moving_average_window)
        self.left_angle_window = deque(maxlen=self.moving_average_window)
        self.right_trend_window = deque(maxlen=self.trend_window_samples)

        self.alreadyGivenFeedback = 0        
        self.min_feedback_state = FEEDBACK_OFF
        self.max_feedback_state = FEEDBACK_OFF
        self.last_min_feedback_iter = -self.cooldown_iters
        self.last_max_feedback_iter = -self.cooldown_iters

    ###########################################################
    # CHECK NODE CONNECTIONS
    ###########################################################
    def check_status(self):
        sensors_count = self.get_sensors_count()
        feedback_count = self.get_feedback_count()
        err_msg = ""
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
        data = self.my_sage.get_next_data()

        # Get Quaternion Data
        self.pelvis_quat = get_rotation(data, self.NodeNum_pelvis)
        self.right_thigh_quat = get_rotation(data, self.NodeNum_right_thigh)
        self.left_thigh_quat = get_rotation(data, self.NodeNum_left_thigh)

        # Calibrate to find BS_q, sensor to body segment alignment quaternions on 1st iteration
        if self.iteration == 0:
            self.right_joint_angles.calibrate(self.pelvis_quat, self.right_thigh_quat)
            self.left_joint_angles.calibrate(self.pelvis_quat, self.left_thigh_quat)

        # Calculate Extension angles
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
        self.update_right_hip_motion()
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

        # Give haptic feedback (turn feedback nodes on/off)
        if self.config["feedback_enabled"]:
            self.give_feedback()
        else:
            self.min_feedback_state = FEEDBACK_OFF
            self.max_feedback_state = FEEDBACK_OFF

        time_now = self.iteration / self.DATARATE  # time in seconds
        self.emit_orientation_debug(time_now, data)

        my_data = {
            'time': [time_now],
            "min_threshold": [self.min_threshold],
            "min_feedback_state": [self.min_feedback_state],
            "Hip_ext": [self.right_Hip_ext],
            "filtered_Hip_ext": [self.filtered_right_Hip_ext],
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
            "feedback_mode_code": [self.feedback_mode_code],
            "feedback_metric": [self.feedback_metric],
            "feedback_reason_code": [self.feedback_reason_code],
            "gyro_mag": [self.right_gyro_mag],
            "acc_mag": [self.right_acc_mag],
            "right_gyro_mag": [self.right_gyro_mag],
            "left_gyro_mag": [self.left_gyro_mag],
            "right_acc_mag": [self.right_acc_mag],
            "left_acc_mag": [self.left_acc_mag],
            "debug_orientation_enabled_state": [int(self.debug_orientation_enabled)],
            "debug_orientation_udp_enabled_state": [int(self.debug_orientation_udp_enabled)],
            "debug_orientation_udp_send_count": [self.debug_orientation_udp_send_count],
            "debug_orientation_udp_error_count": [self.debug_orientation_udp_error_count],
            "debug_orientation_udp_last_error_code": [self.debug_orientation_udp_last_error_code],
            "debug_orientation_udp_target_port": [self.debug_orientation_udp_port],
            "debug_orientation_udp_target_last_octet": [self.debug_orientation_udp_target_last_octet],
            "target_met": [int(self.min_feedback_state == 0 and self.max_feedback_state == 0)],
        }

        self.my_sage.save_data(data, my_data)
        self.my_sage.send_stream_data(data, my_data)

        self.iteration += 1
        return True
    #############################################################
    # MANAGE FEEDBACK FOR APP
    #############################################################
    def toggle_feedback(self, feedbackNode=0, duration=1, feedback_state=FEEDBACK_OFF):
        if feedback_state:
            self.my_sage.feedback_on(feedbackNode, duration)
        else:
            self.my_sage.feedback_off(feedbackNode)

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
                "target_phase_state": self.target_phase_state,
                "feedback_phase_state": self.feedback_phase_state,
                "min_feedback_state": self.min_feedback_state,
                "feedback_reason_code": self.feedback_reason_code,
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
            return self.right_gyro_mag
        if self.feedback_mode == "acc_mag":
            self.feedback_mode_code = 2
            return self.right_acc_mag
        self.feedback_mode_code = 0
        return self.filtered_right_Hip_ext

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

    def update_right_hip_motion(self):
        if self.previous_filtered_right_Hip_ext is None:
            self.right_hip_velocity = 0.0
        else:
            self.right_hip_velocity = (
                self.filtered_right_Hip_ext - self.previous_filtered_right_Hip_ext
            )
        self.previous_filtered_right_Hip_ext = self.filtered_right_Hip_ext

        self.right_trend_window.append(self.filtered_right_Hip_ext)
        if len(self.right_trend_window) > 1:
            self.right_hip_trend = self.filtered_right_Hip_ext - self.right_trend_window[0]
        else:
            self.right_hip_trend = 0.0

        if self.extension_direction == "increasing":
            is_extending = (
                self.right_hip_velocity > self.extension_velocity_threshold
                or self.right_hip_trend > self.extension_trend_threshold
            )
            is_flexing = (
                self.right_hip_velocity < -self.reset_velocity_threshold
                or self.right_hip_trend < -self.reset_trend_threshold
            )
        else:
            is_extending = (
                self.right_hip_velocity < -self.extension_velocity_threshold
                or self.right_hip_trend < -self.extension_trend_threshold
            )
            is_flexing = (
                self.right_hip_velocity > self.reset_velocity_threshold
                or self.right_hip_trend > self.reset_trend_threshold
            )

        self.right_hip_extending_state = int(is_extending)
        self.right_hip_flexing_state = int(is_flexing)

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
        movement_ok = True
        if self.movement_gate_enabled:
            movement_ok = self.right_gyro_mag >= self.movement_gate_gyro_threshold
        self.target_phase_state = int(
            self.right_leg_back_state and self.left_leg_forward_state and movement_ok
        )

    def give_feedback(self):
        self.update_target_phase()
        self.feedback_metric = self.get_feedback_metric()

        if self.right_hip_flexing_state:
            self.feedback_phase_state = PHASE_WAITING
            self.feedback_reason_code = 6
            self.toggle_all_feedback_off()
            self.min_feedback_state = FEEDBACK_OFF
            self.max_feedback_state = FEEDBACK_OFF
            return

        if self.phase_gate_enabled and not self.target_phase_state:
            self.feedback_reason_code = 3
            self.feedback_phase_state = PHASE_WAITING
            self.toggle_all_feedback_off()
            self.min_feedback_state = FEEDBACK_OFF
            self.max_feedback_state = FEEDBACK_OFF
            return

        if (
            self.feedback_phase_state == PHASE_WAITING
            and self.right_hip_extending_state
        ):
            self.feedback_phase_state = PHASE_EXTENDING

        if self.feedback_phase_state == PHASE_WAITING:
            self.feedback_reason_code = 4
            self.toggle_all_feedback_off()
            self.min_feedback_state = FEEDBACK_OFF
            self.max_feedback_state = FEEDBACK_OFF
            return

        if self.feedback_phase_state == PHASE_QUALIFIED:
            self.feedback_reason_code = 5
            self.toggle_all_feedback_off()
            self.min_feedback_state = FEEDBACK_OFF
            self.max_feedback_state = FEEDBACK_OFF
            return

        if self.feedback_trigger_direction == "below":
            next_min_state = int(self.below_min_with_hysteresis(self.feedback_metric))
        else:
            next_min_state = int(self.above_min_with_hysteresis(self.feedback_metric))
        next_max_state = FEEDBACK_OFF

        if next_min_state:
            self.feedback_reason_code = 1
        else:
            self.feedback_reason_code = 0
            self.feedback_phase_state = PHASE_QUALIFIED

        if next_min_state:
            if self.iteration - self.last_min_feedback_iter >= self.cooldown_iters:
                self.toggle_feedback(
                    self.NodeNum_feedback_min,
                    duration=self.pulse_length,
                    feedback_state=FEEDBACK_ON,
                )
                self.last_min_feedback_iter = self.iteration
        elif self.min_feedback_state:
            self.toggle_feedback(self.NodeNum_feedback_min, feedback_state=FEEDBACK_OFF)

        if self.NodeNum_feedback_max is not None and next_max_state:
            if self.iteration - self.last_max_feedback_iter >= self.cooldown_iters:
                self.toggle_feedback(
                    self.NodeNum_feedback_max,
                    duration=self.pulse_length,
                    feedback_state=FEEDBACK_ON,
                )
                self.last_max_feedback_iter = self.iteration
        elif self.NodeNum_feedback_max is not None and self.max_feedback_state:
            self.toggle_feedback(self.NodeNum_feedback_max, feedback_state=FEEDBACK_OFF)

        self.min_feedback_state = next_min_state
        self.max_feedback_state = next_max_state

        # if no feedback should be given, make sure to toggle all feedback off
        # Note: This can only happen if both are 0
        if self.min_feedback_state == self.max_feedback_state:
            self.toggle_all_feedback_off()

    def toggle_all_feedback_off(self):
        self.toggle_feedback(self.NodeNum_feedback_min, feedback_state=FEEDBACK_OFF)
        if self.NodeNum_feedback_max is not None:
            self.toggle_feedback(self.NodeNum_feedback_max, feedback_state=FEEDBACK_OFF)

    #############################################################
    # UPON STOPPING THE APP
    # If you have anything that needs to happen after the app stops,
    # you can uncomment the following lines and add the code in there.
    # This function will be called after the data file is saved and
    # can be read back in for reporting purposes if needed.
    #############################################################
    # def on_stop_event(self, stop_time):
    #     print(f"In On Stop Event: {stop_time}")
