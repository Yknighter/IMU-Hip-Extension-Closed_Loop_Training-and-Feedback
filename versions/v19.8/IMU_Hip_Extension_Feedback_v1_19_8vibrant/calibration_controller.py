CALIBRATION_DISABLED = 0
CALIBRATION_COLLECTING = 1
CALIBRATION_READY = 2
CALIBRATION_CONFIRMED = 3


class CalibrationController:
    def __init__(
        self,
        enabled,
        duration_sec,
        min_target_phase_sec,
        min_steps,
        percentile,
        target_offset_deg,
        limit,
        direction,
        datarate,
        max_duration_sec=0.0,
    ):
        self.enabled = bool(enabled)
        self.duration_sec = float(duration_sec)
        self.max_duration_sec = float(max_duration_sec)
        self.min_target_phase_sec = float(min_target_phase_sec)
        self.min_steps = int(min_steps)
        self.percentile = max(0.0, min(1.0, float(percentile)))
        self.target_offset_deg = abs(float(target_offset_deg))
        self.limit = float(limit)
        self.direction = direction
        self.datarate = float(datarate)

        self.duration_samples = max(1, int(round(self.duration_sec * self.datarate)))
        self.max_duration_samples = (
            max(1, int(round(self.max_duration_sec * self.datarate)))
            if self.max_duration_sec > 0
            else 0
        )
        self.min_target_phase_samples = max(
            0, int(round(self.min_target_phase_sec * self.datarate))
        )
        self.state = (
            CALIBRATION_COLLECTING if self.enabled else CALIBRATION_DISABLED
        )
        self.sample_count = 0
        self.target_phase_samples = 0
        self.target_phase_sec = 0.0
        self.step_count = 0
        self.step_peaks = []
        self.all_angles = []
        self.suggested_threshold = None
        self.confirmed_threshold = None
        self._recent_angles = []

    def update(self, angle, target_phase_state):
        if not self.enabled or self.state in (
            CALIBRATION_READY,
            CALIBRATION_CONFIRMED,
        ):
            return self.suggested_threshold

        self.sample_count += 1
        self.all_angles.append(float(angle))
        self.target_phase_samples = self.sample_count
        self.target_phase_sec = self.sample_count / self.datarate
        self._append_angle_extremum(float(angle))

        if self._has_enough_data() or self._reached_max_duration():
            self.suggested_threshold = self._suggest_threshold()
            self.state = CALIBRATION_READY
        return self.suggested_threshold

    def confirm(self, threshold=None):
        if threshold is None:
            threshold = self.suggested_threshold
        if threshold is None:
            return None
        self.confirmed_threshold = self._clamp(float(threshold))
        self.state = CALIBRATION_CONFIRMED
        return self.confirmed_threshold

    def _append_angle_extremum(self, angle):
        self._recent_angles.append(float(angle))
        if len(self._recent_angles) < 3:
            return
        previous, middle, current = self._recent_angles[-3:]
        if self.direction == "decreasing":
            is_extremum = middle <= previous and middle <= current and (
                middle < previous or middle < current
            )
        else:
            is_extremum = middle >= previous and middle >= current and (
                middle > previous or middle > current
            )
        if is_extremum:
            self.step_peaks.append(middle)
            self._recent_angles = self._recent_angles[-2:]
        else:
            self._recent_angles = self._recent_angles[-3:]
        self.step_count = len(self.step_peaks)

    def _has_enough_data(self):
        if self.sample_count < self.duration_samples:
            return False
        return True

    def _reached_max_duration(self):
        return self.max_duration_samples > 0 and self.sample_count >= self.max_duration_samples

    def _suggest_threshold(self):
        values = self.step_peaks if self.step_peaks else self.all_angles
        if not values:
            return None
        sorted_values = sorted(values)
        index = int(round((len(sorted_values) - 1) * self.percentile))
        base_value = sorted_values[index]
        if self.direction == "decreasing":
            return self._clamp(base_value - self.target_offset_deg)
        return self._clamp(base_value + self.target_offset_deg)

    def _clamp(self, value):
        if self.direction == "decreasing":
            return round(max(float(value), self.limit), 6)
        return round(min(float(value), self.limit), 6)
