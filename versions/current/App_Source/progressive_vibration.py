class VibrationDecision:
    def __init__(
        self,
        should_vibrate,
        progress_ratio,
        interval_ms,
        pulse_duration,
        strength,
        terminal_goal_met,
    ):
        self.should_vibrate = bool(should_vibrate)
        self.progress_ratio = float(progress_ratio)
        self.interval_ms = int(round(interval_ms))
        self.pulse_duration = pulse_duration
        self.strength = strength
        self.terminal_goal_met = bool(terminal_goal_met)


class ProgressiveVibrationController:
    def __init__(
        self,
        enabled,
        min_interval_ms,
        max_interval_ms,
        curve,
        pulse_duration,
        strength,
        terminal_feedback_mode,
        direction,
        datarate,
    ):
        self.enabled = bool(enabled)
        self.min_interval_ms = float(min_interval_ms)
        self.max_interval_ms = max(self.min_interval_ms, float(max_interval_ms))
        self.curve = max(0.01, float(curve))
        self.pulse_duration = pulse_duration
        self.strength = strength
        self.terminal_feedback_mode = terminal_feedback_mode
        self.direction = direction
        self.datarate = float(datarate)
        self.last_vibration_sample = None
        self.terminal_pulse_sent = False

    def reset(self):
        self.last_vibration_sample = None
        self.terminal_pulse_sent = False

    def update(
        self,
        angle,
        training_threshold,
        terminal_threshold,
        sample_index,
        allow_feedback=True,
    ):
        progress_ratio = self.progress_ratio(
            angle,
            training_threshold,
            terminal_threshold,
        )
        terminal_goal_met = progress_ratio >= 1.0
        interval_ms = self.interval_ms(progress_ratio)
        should_vibrate = False

        if self.enabled and allow_feedback:
            if terminal_goal_met:
                should_vibrate = self._terminal_should_vibrate()
            else:
                should_vibrate = self._interval_due(sample_index, interval_ms)

        if should_vibrate:
            self.last_vibration_sample = int(sample_index)
            if terminal_goal_met:
                self.terminal_pulse_sent = True

        return VibrationDecision(
            should_vibrate=should_vibrate,
            progress_ratio=progress_ratio,
            interval_ms=interval_ms,
            pulse_duration=self.pulse_duration,
            strength=self.strength,
            terminal_goal_met=terminal_goal_met,
        )

    def progress_ratio(self, angle, training_threshold, terminal_threshold):
        current = float(angle)
        start = float(training_threshold)
        terminal = float(terminal_threshold)
        if self.direction == "decreasing":
            current = -current
            start = -start
            terminal = -terminal
        span = terminal - start
        if span <= 0:
            return 1.0 if current >= terminal else 0.0
        ratio = (current - start) / span
        return round(max(0.0, min(1.0, ratio)), 6)

    def interval_ms(self, progress_ratio):
        eased = max(0.0, min(1.0, float(progress_ratio))) ** self.curve
        return int(round(
            self.min_interval_ms
            + (self.max_interval_ms - self.min_interval_ms) * eased
        ))

    def _terminal_should_vibrate(self):
        if self.terminal_feedback_mode == "off":
            return False
        if self.terminal_feedback_mode == "single_pulse":
            return not self.terminal_pulse_sent
        return True

    def _interval_due(self, sample_index, interval_ms):
        if self.last_vibration_sample is None:
            return True
        interval_samples = max(
            1,
            int(round(float(interval_ms) * self.datarate / 1000.0)),
        )
        return int(sample_index) - self.last_vibration_sample >= interval_samples
