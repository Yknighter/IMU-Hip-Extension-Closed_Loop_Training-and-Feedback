import math


REASON_DISABLED = 0
REASON_ADJUSTED = 1
REASON_NOT_ENOUGH_TARGET_PHASE = 2
REASON_SUCCESS_RATIO_TOO_LOW = 3
REASON_AT_LIMIT = 4
REASON_COLLECTING = 5
REASON_ASSESSMENT_COMPLETE = 6

MODE_DISABLED = 0
MODE_ASSESSMENT = 1
MODE_TRAINING = 2


class AdaptiveThresholdController:
    def __init__(
        self,
        enabled,
        initial_threshold,
        limit,
        step_deg,
        direction,
        interval_sec,
        success_ratio_required,
        min_target_phase_sec,
        datarate,
        assessment_sec=60.0,
        assessment_percentile=0.5,
        assessment_rounding="floor",
        min_start_threshold=0.0,
        min_valid_steps_per_window=0,
    ):
        self.enabled = bool(enabled)
        self.initial_threshold = float(initial_threshold)
        self.limit = float(limit)
        self.step_deg = self._clamp_step_deg(step_deg)
        self.direction = direction
        self.interval_sec = float(interval_sec)
        self.success_ratio_required = float(success_ratio_required)
        self.min_target_phase_sec = float(min_target_phase_sec)
        self.datarate = float(datarate)
        self.assessment_sec = float(assessment_sec)
        self.assessment_percentile = max(0.0, min(1.0, float(assessment_percentile)))
        self.assessment_rounding = str(assessment_rounding)
        self.min_start_threshold = float(min_start_threshold)
        self.min_valid_steps_per_window = max(0, int(min_valid_steps_per_window))

        self.interval_samples = max(1, int(round(self.interval_sec * self.datarate)))
        self.assessment_samples_required = max(
            1, int(round(self.assessment_sec * self.datarate))
        )
        self.min_target_phase_samples = max(
            self.min_valid_steps_per_window,
            int(round(self.min_target_phase_sec * self.datarate)),
        )
        self.assessed_threshold = 0.0
        self.current_threshold = self._clamp(self.initial_threshold)
        self.stage = 0
        self.adjust_count = 0
        self.reason_code = REASON_DISABLED if not self.enabled else REASON_COLLECTING
        self.success_ratio = 0.0
        self.success_ratio_percent = 0.0
        self.eval_elapsed_sec = 0.0
        self.eval_target_phase_sec = 0.0
        self.current_level = 1
        self.mode = MODE_DISABLED if not self.enabled else MODE_ASSESSMENT
        self.assessment_elapsed_sec = 0.0
        self.assessment_sample_count = 0
        self.assessment_latest_extension = 0.0
        self.assessment_extension_sample_count = 0
        self.assessment_valid_step_count = 0
        self.latest_step_peak_deg = 0.0
        self.window_peak_sum_deg = 0.0
        self.last_window_peak_sum_deg = 0.0
        self.last_step_success_state = 0
        self.window_valid_samples = 0
        self.window_success_samples = 0
        self.last_window_valid_samples = 0
        self.last_window_success_samples = 0
        self._assessment_values = []
        self._elapsed_samples = 0
        self._target_phase_samples = 0
        self._success_samples = 0

    def update_assessment_sample(self, extension_deg):
        self.update_time_sample()
        if not self.enabled:
            self.reason_code = REASON_DISABLED
            return self.current_threshold, False
        if self.mode != MODE_ASSESSMENT:
            return self.current_threshold, False

        extension = float(extension_deg)
        self.assessment_latest_extension = extension
        if extension > 0.0:
            self._assessment_values.append(extension)
        self.assessment_extension_sample_count = len(self._assessment_values)

        if self.assessment_sample_count >= self.assessment_samples_required:
            self._complete_assessment()
        return self.current_threshold, False

    def update_assessment_step(self, valid_step_state, peak_deg):
        if not self.enabled:
            self.reason_code = REASON_DISABLED
            return self.current_threshold, False
        if self.mode != MODE_ASSESSMENT:
            return self.current_threshold, False
        if not valid_step_state:
            return self.current_threshold, False

        peak = float(peak_deg)
        self.assessment_latest_extension = peak
        self.latest_step_peak_deg = peak
        self._assessment_values.append(peak)
        self.assessment_extension_sample_count = len(self._assessment_values)
        self.assessment_valid_step_count = self.assessment_extension_sample_count

        if self.assessment_sample_count >= self.assessment_samples_required:
            self._complete_assessment()
        return self.current_threshold, False

    def update(self, target_phase_state, feedback_phase_state, min_feedback_state):
        success_state = (
            int(feedback_phase_state) == 2 and int(min_feedback_state) == 0
        )
        return self.update_success_sample(
            valid_sample_state=target_phase_state,
            success_state=success_state,
        )

    def update_success_sample(self, valid_sample_state, success_state):
        self.update_time_sample()
        if not self.enabled:
            self.reason_code = REASON_DISABLED
            return self.current_threshold, False
        if self.mode != MODE_TRAINING:
            return self.current_threshold, False

        if valid_sample_state:
            self._target_phase_samples += 1
            if success_state:
                self._success_samples += 1

        self.window_valid_samples = self._target_phase_samples
        self.window_success_samples = self._success_samples
        self.eval_elapsed_sec = self._elapsed_samples / self.datarate
        self.eval_target_phase_sec = self._target_phase_samples / self.datarate

        return self.current_threshold, False

    def update_training_step(self, valid_step_state, success_state, peak_deg):
        if not self.enabled:
            self.reason_code = REASON_DISABLED
            return self.current_threshold, False
        if self.mode != MODE_TRAINING:
            return self.current_threshold, False

        if valid_step_state:
            self._target_phase_samples += 1
            self.latest_step_peak_deg = float(peak_deg)
            self.window_peak_sum_deg += float(peak_deg)
            if success_state:
                self._success_samples += 1
            self.last_step_success_state = int(bool(success_state))

        self.window_valid_samples = self._target_phase_samples
        self.window_success_samples = self._success_samples
        self.eval_target_phase_sec = self._target_phase_samples
        return self.current_threshold, False

    def update_time_sample(self, allow_evaluation=True):
        if not self.enabled:
            self.reason_code = REASON_DISABLED
            return self.current_threshold, False

        if self.mode == MODE_ASSESSMENT:
            self.assessment_sample_count += 1
            self.assessment_elapsed_sec = self.assessment_sample_count / self.datarate
            if self.assessment_sample_count >= self.assessment_samples_required:
                self._complete_assessment()
            return self.current_threshold, False

        if self.mode != MODE_TRAINING:
            return self.current_threshold, False

        self._elapsed_samples += 1
        self.eval_elapsed_sec = self._elapsed_samples / self.datarate
        adjusted = False
        if self._elapsed_samples >= self.interval_samples and allow_evaluation:
            adjusted = self._evaluate_interval()
        return self.current_threshold, adjusted

    def reset_training_window(self):
        self._elapsed_samples = 0
        self._target_phase_samples = 0
        self._success_samples = 0
        self.window_peak_sum_deg = 0.0
        self.window_valid_samples = 0
        self.window_success_samples = 0
        self.eval_elapsed_sec = 0.0
        self.eval_target_phase_sec = 0.0

    def _complete_assessment(self):
        if self._assessment_values:
            assessed = self._percentile(
                self._assessment_values, self.assessment_percentile
            )
            assessed = self._round_assessed_threshold(assessed)
        else:
            assessed = self.min_start_threshold
        assessed = max(self.min_start_threshold, assessed)
        self.assessed_threshold = self._clamp(assessed)
        self.current_threshold = self.assessed_threshold
        self.mode = MODE_TRAINING
        self.stage = 0
        self.current_level = 1
        self.adjust_count = 0
        self.reason_code = REASON_ASSESSMENT_COMPLETE
        self.reset_training_window()

    def _evaluate_interval(self):
        self.last_window_valid_samples = self._target_phase_samples
        self.last_window_success_samples = self._success_samples
        self.last_window_peak_sum_deg = self.window_peak_sum_deg
        if self._target_phase_samples <= 0:
            self.success_ratio = 0.0
        else:
            self.success_ratio = self._success_samples / float(self._target_phase_samples)
        self.success_ratio_percent = round(self.success_ratio * 100.0, 6)

        adjusted = False
        if self._target_phase_samples < self.min_target_phase_samples:
            self.reason_code = REASON_NOT_ENOUGH_TARGET_PHASE
        elif self.success_ratio < self.success_ratio_required:
            self.reason_code = REASON_SUCCESS_RATIO_TOO_LOW
        else:
            adjusted = self._advance_threshold()

        self.reset_training_window()
        return adjusted

    def _advance_threshold(self):
        next_threshold = self._next_threshold()
        if next_threshold == self.current_threshold:
            self.reason_code = REASON_AT_LIMIT
            return False
        self.current_threshold = next_threshold
        self.stage += 1
        self.current_level = self.stage + 1
        self.adjust_count += 1
        self.reason_code = REASON_ADJUSTED
        return True

    def _next_threshold(self):
        if self.direction == "decreasing":
            return self._clamp(self.current_threshold - self.step_deg)
        return self._clamp(self.current_threshold + self.step_deg)

    def _clamp_step_deg(self, value):
        return max(1.0, min(14.0, abs(float(value))))

    def _clamp(self, value):
        if self.direction == "decreasing":
            return round(max(float(value), self.limit), 6)
        return round(min(float(value), self.limit), 6)

    def _percentile(self, values, percentile):
        ordered = sorted(float(value) for value in values)
        if not ordered:
            return self.initial_threshold
        index = int(round((len(ordered) - 1) * float(percentile)))
        index = max(0, min(len(ordered) - 1, index))
        return ordered[index]

    def _round_assessed_threshold(self, value):
        value = float(value)
        if self.assessment_rounding == "round":
            return round(value)
        if self.assessment_rounding == "ceil":
            return math.ceil(value)
        return math.floor(value)

    def reset(self, initial_threshold=None):
        if initial_threshold is not None:
            self.initial_threshold = float(initial_threshold)
        self.assessed_threshold = 0.0
        self.current_threshold = self._clamp(self.initial_threshold)
        self.stage = 0
        self.current_level = 1
        self.adjust_count = 0
        self.reason_code = REASON_DISABLED if not self.enabled else REASON_COLLECTING
        self.success_ratio = 0.0
        self.success_ratio_percent = 0.0
        self.eval_elapsed_sec = 0.0
        self.eval_target_phase_sec = 0.0
        self.mode = MODE_DISABLED if not self.enabled else MODE_ASSESSMENT
        self.assessment_elapsed_sec = 0.0
        self.assessment_sample_count = 0
        self.assessment_latest_extension = 0.0
        self.assessment_extension_sample_count = 0
        self.assessment_valid_step_count = 0
        self.latest_step_peak_deg = 0.0
        self.window_peak_sum_deg = 0.0
        self.last_window_peak_sum_deg = 0.0
        self.last_step_success_state = 0
        self.window_valid_samples = 0
        self.window_success_samples = 0
        self.last_window_valid_samples = 0
        self.last_window_success_samples = 0
        self._assessment_values = []
        self.reset_training_window()
        return self.current_threshold
