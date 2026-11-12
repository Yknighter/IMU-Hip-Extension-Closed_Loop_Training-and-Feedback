FEEDBACK_OFF = 0
FEEDBACK_ON = 1

LEVEL_UNKNOWN = 0
LEVEL_FAR = 1
LEVEL_NEAR = 2
LEVEL_SUCCESS = 3

STATE_DISARMED = 0
STATE_ARMED = 1
STATE_SUCCESS_LATCHED = 2

REASON_DISABLED = 40
REASON_DISARMED_AT_TARGET = 41
REASON_WAITING_RESET = 42
REASON_LEVEL1_FAR = 43
REASON_LEVEL2_NEAR = 44
REASON_LEVEL2_BUFFER = 45
REASON_SUCCESS_DWELL = 46
REASON_SUCCESS_PULSE = 47
REASON_SUCCESS_LATCHED = 48


class DeficitFeedbackDecision:
    def __init__(
        self,
        should_vibrate,
        pulse_duration,
        strength,
        feedback_level,
        machine_state,
        deficit_deg,
        progress_ratio,
        feedback_interval_ms,
        feedback_reason_code,
        armed_state,
        success_latched_state,
        target_dwell_state,
        reset_dwell_state,
    ):
        self.should_vibrate = bool(should_vibrate)
        self.pulse_duration = float(pulse_duration)
        self.strength = int(strength)
        self.feedback_level = int(feedback_level)
        self.machine_state = int(machine_state)
        self.deficit_deg = float(deficit_deg)
        self.progress_ratio = float(progress_ratio)
        self.feedback_interval_ms = int(round(feedback_interval_ms))
        self.feedback_reason_code = int(feedback_reason_code)
        self.armed_state = int(armed_state)
        self.success_latched_state = int(success_latched_state)
        self.target_dwell_state = int(target_dwell_state)
        self.reset_dwell_state = int(reset_dwell_state)


class DeficitFeedbackStrategy:
    def __init__(
        self,
        enabled,
        datarate,
        target_direction,
        near_margin_deg,
        far_margin_deg,
        reset_margin_deg,
        target_dwell_ms,
        reset_dwell_ms,
        success_refractory_ms,
        level1_interval_ms,
        level1_duration,
        level1_strength,
        level2_min_interval_ms,
        level2_max_interval_ms,
        level2_duration,
        level2_strength,
        level3_duration,
        level3_strength,
        success_vibration_enabled=False,
    ):
        self.enabled = bool(enabled)
        self.datarate = float(datarate)
        self.target_direction = target_direction
        self.near_margin_deg = max(0.0, float(near_margin_deg))
        self.far_margin_deg = max(self.near_margin_deg, float(far_margin_deg))
        self.reset_margin_deg = max(0.0, float(reset_margin_deg))
        self.target_dwell_samples = self._ms_to_samples(target_dwell_ms)
        self.reset_dwell_samples = self._ms_to_samples(reset_dwell_ms)
        self.success_refractory_samples = self._ms_to_samples(success_refractory_ms)
        self.level1_interval_ms = float(level1_interval_ms)
        self.level1_duration = float(level1_duration)
        self.level1_strength = int(level1_strength)
        self.level2_min_interval_ms = float(level2_min_interval_ms)
        self.level2_max_interval_ms = max(
            self.level2_min_interval_ms,
            float(level2_max_interval_ms),
        )
        self.level2_duration = float(level2_duration)
        self.level2_strength = int(level2_strength)
        self.level3_duration = float(level3_duration)
        self.level3_strength = int(level3_strength)
        self.success_vibration_enabled = bool(success_vibration_enabled)
        self.reset()

    def reset(self):
        self.machine_state = STATE_DISARMED
        self._reset_started_sample = None
        self._target_started_sample = None
        self._last_vibration_sample = None
        self._last_success_sample = None

    def rearm_after_external_reset(self):
        self.machine_state = STATE_ARMED
        self._reset_started_sample = None
        self._target_started_sample = None

    def update(self, angle, target_threshold, sample_index, allow_feedback=True):
        sample_index = int(sample_index)
        deficit = self.deficit_deg(angle, target_threshold)
        level = self.classify_deficit(deficit)
        progress = self.progress_ratio(deficit)

        if not self.enabled or not allow_feedback:
            return self._decision(
                should_vibrate=False,
                duration=0,
                strength=0,
                level=LEVEL_UNKNOWN,
                deficit=deficit,
                progress=progress,
                interval_ms=0,
                reason=REASON_DISABLED,
            )

        if self.machine_state == STATE_DISARMED:
            if self._reset_dwell_met(deficit, sample_index):
                self.machine_state = STATE_ARMED
            else:
                reason = (
                    REASON_DISARMED_AT_TARGET
                    if level == LEVEL_SUCCESS
                    else REASON_WAITING_RESET
                )
                return self._decision(
                    should_vibrate=False,
                    duration=0,
                    strength=0,
                    level=level,
                    deficit=deficit,
                    progress=progress,
                    interval_ms=0,
                    reason=reason,
                )

        if self.machine_state == STATE_SUCCESS_LATCHED:
            if self._reset_dwell_met(deficit, sample_index):
                self.machine_state = STATE_ARMED
                self._target_started_sample = None
            else:
                return self._decision(
                    should_vibrate=False,
                    duration=0,
                    strength=0,
                    level=level,
                    deficit=deficit,
                    progress=progress,
                    interval_ms=0,
                    reason=REASON_SUCCESS_LATCHED,
                )

        if level == LEVEL_SUCCESS:
            self._reset_started_sample = None
            return self._success_decision(deficit, progress, sample_index)

        self._target_started_sample = None
        if level == LEVEL_FAR:
            return self._interval_decision(
                deficit=deficit,
                progress=progress,
                sample_index=sample_index,
                level=LEVEL_FAR,
                interval_ms=self.level1_interval_ms,
                duration=self.level1_duration,
                strength=self.level1_strength,
                reason=REASON_LEVEL1_FAR,
            )
        if level == LEVEL_NEAR:
            interval_ms = self.level2_interval_ms(deficit)
            return self._interval_decision(
                deficit=deficit,
                progress=progress,
                sample_index=sample_index,
                level=LEVEL_NEAR,
                interval_ms=interval_ms,
                duration=self.level2_duration,
                strength=self.level2_strength,
                reason=REASON_LEVEL2_NEAR,
            )
        return self._decision(
            should_vibrate=False,
            duration=0,
            strength=0,
            level=LEVEL_NEAR,
            deficit=deficit,
            progress=progress,
            interval_ms=0,
            reason=REASON_LEVEL2_BUFFER,
        )

    def deficit_deg(self, angle, target_threshold):
        if self.target_direction == "increasing":
            return float(target_threshold) - float(angle)
        return float(angle) - float(target_threshold)

    def classify_deficit(self, deficit):
        deficit = float(deficit)
        if deficit <= 0:
            return LEVEL_SUCCESS
        if deficit >= self.far_margin_deg:
            return LEVEL_FAR
        if deficit >= self.near_margin_deg:
            return LEVEL_NEAR
        return LEVEL_UNKNOWN

    def progress_ratio(self, deficit):
        if self.far_margin_deg <= 0:
            return 1.0
        ratio = (self.far_margin_deg - max(0.0, float(deficit))) / self.far_margin_deg
        return round(max(0.0, min(1.0, ratio)), 6)

    def level2_interval_ms(self, deficit):
        span = max(0.000001, self.far_margin_deg - self.near_margin_deg)
        closeness = (self.far_margin_deg - float(deficit)) / span
        closeness = max(0.0, min(1.0, closeness))
        interval = self.level2_max_interval_ms - (
            self.level2_max_interval_ms - self.level2_min_interval_ms
        ) * closeness
        return int(round(interval))

    def _success_decision(self, deficit, progress, sample_index):
        if self._target_started_sample is None:
            self._target_started_sample = int(sample_index)
        dwell_met = (
            int(sample_index) - int(self._target_started_sample)
        ) >= self.target_dwell_samples
        refractory_met = (
            self._last_success_sample is None
            or int(sample_index) - int(self._last_success_sample)
            >= self.success_refractory_samples
        )
        if dwell_met and refractory_met:
            self.machine_state = STATE_SUCCESS_LATCHED
            self._last_success_sample = int(sample_index)
            if self.success_vibration_enabled:
                self._last_vibration_sample = int(sample_index)
            return self._decision(
                should_vibrate=self.success_vibration_enabled,
                duration=self.level3_duration if self.success_vibration_enabled else 0,
                strength=self.level3_strength if self.success_vibration_enabled else 0,
                level=LEVEL_SUCCESS,
                deficit=deficit,
                progress=1.0,
                interval_ms=0,
                reason=REASON_SUCCESS_PULSE,
            )
        return self._decision(
            should_vibrate=False,
            duration=0,
            strength=0,
            level=LEVEL_SUCCESS,
            deficit=deficit,
            progress=progress,
            interval_ms=0,
            reason=REASON_SUCCESS_DWELL,
        )

    def _interval_decision(
        self,
        deficit,
        progress,
        sample_index,
        level,
        interval_ms,
        duration,
        strength,
        reason,
    ):
        should_vibrate = self._interval_due(sample_index, interval_ms)
        if should_vibrate:
            self._last_vibration_sample = int(sample_index)
        return self._decision(
            should_vibrate=should_vibrate,
            duration=duration if should_vibrate else 0,
            strength=strength if should_vibrate else 0,
            level=level,
            deficit=deficit,
            progress=progress,
            interval_ms=interval_ms,
            reason=reason,
        )

    def _reset_dwell_met(self, deficit, sample_index):
        if float(deficit) < self.reset_margin_deg:
            self._reset_started_sample = None
            return False
        if self._reset_started_sample is None:
            self._reset_started_sample = int(sample_index)
        return (
            int(sample_index) - int(self._reset_started_sample)
        ) >= self.reset_dwell_samples

    def _interval_due(self, sample_index, interval_ms):
        if self._last_vibration_sample is None:
            return True
        return int(sample_index) - int(self._last_vibration_sample) >= self._ms_to_samples(
            interval_ms
        )

    def _ms_to_samples(self, value):
        return max(1, int(round(float(value) * self.datarate / 1000.0)))

    def _decision(
        self,
        should_vibrate,
        duration,
        strength,
        level,
        deficit,
        progress,
        interval_ms,
        reason,
    ):
        target_dwell_state = int(self._target_started_sample is not None)
        reset_dwell_state = int(self._reset_started_sample is not None)
        return DeficitFeedbackDecision(
            should_vibrate=should_vibrate,
            pulse_duration=duration,
            strength=strength,
            feedback_level=level,
            machine_state=self.machine_state,
            deficit_deg=deficit,
            progress_ratio=progress,
            feedback_interval_ms=interval_ms,
            feedback_reason_code=reason,
            armed_state=int(self.machine_state == STATE_ARMED),
            success_latched_state=int(self.machine_state == STATE_SUCCESS_LATCHED),
            target_dwell_state=target_dwell_state,
            reset_dwell_state=reset_dwell_state,
        )
