try:
    from .gait_phase_controller import (
        GAIT_STANCE,
        GAIT_SWING,
        LEVEL_ABOVE,
        LEVEL_BELOW,
        LEVEL_UNKNOWN,
        LEVEL_WITHIN,
        STANCE_FOOT_FLAT,
        STANCE_HEEL_OFF,
        STANCE_HEEL_STRIKE,
        STANCE_MID,
        STANCE_TOE_OFF,
        SWING_ACCELERATION,
        SWING_DECELERATION,
        SWING_MID,
    )
    from .progressive_vibration import ProgressiveVibrationController
except ImportError:
    from gait_phase_controller import (
        GAIT_STANCE,
        GAIT_SWING,
        LEVEL_ABOVE,
        LEVEL_BELOW,
        LEVEL_UNKNOWN,
        LEVEL_WITHIN,
        STANCE_FOOT_FLAT,
        STANCE_HEEL_OFF,
        STANCE_HEEL_STRIKE,
        STANCE_MID,
        STANCE_TOE_OFF,
        SWING_ACCELERATION,
        SWING_DECELERATION,
        SWING_MID,
    )
    from progressive_vibration import ProgressiveVibrationController

FEEDBACK_OFF = 0
FEEDBACK_ON = 1

REASON_GRADED_DISABLED = 20
REASON_LEVEL1_STANCE = 21
REASON_LEVEL1_WAITING = 22
REASON_LEVEL2_PROGRESSIVE = 23
REASON_LEVEL2_WAITING = 24
REASON_LEVEL3_SWING = 25
REASON_LEVEL3_DECELERATION = 26
REASON_LEVEL3_WAITING = 27


class GradedFeedbackDecision:
    def __init__(
        self,
        posterior_should_vibrate,
        front_should_vibrate,
        posterior_feedback_state,
        front_feedback_state,
        posterior_duration,
        posterior_strength,
        front_duration,
        front_strength,
        feedback_reason_code,
        feedback_progress_ratio,
        feedback_interval_ms,
        terminal_goal_met_state,
    ):
        self.posterior_should_vibrate = bool(posterior_should_vibrate)
        self.front_should_vibrate = bool(front_should_vibrate)
        self.posterior_feedback_state = int(posterior_feedback_state)
        self.front_feedback_state = int(front_feedback_state)
        self.posterior_duration = posterior_duration
        self.posterior_strength = posterior_strength
        self.front_duration = front_duration
        self.front_strength = front_strength
        self.feedback_reason_code = int(feedback_reason_code)
        self.feedback_progress_ratio = float(feedback_progress_ratio)
        self.feedback_interval_ms = int(round(feedback_interval_ms))
        self.terminal_goal_met_state = int(terminal_goal_met_state)


class GradedVibrationStrategy:
    def __init__(
        self,
        enabled,
        datarate,
        ability_range_min_deg,
        ability_range_max_deg,
        direction,
        level1_interval_ms,
        level1_pulse_duration,
        level1_strength,
        level3_interval_ms,
        level3_pulse_duration,
        level3_strength,
        progressive_controller=None,
    ):
        self.enabled = bool(enabled)
        self.datarate = float(datarate)
        self.ability_range_min_deg = float(ability_range_min_deg)
        self.ability_range_max_deg = float(ability_range_max_deg)
        self.direction = direction
        self.level1_interval_ms = float(level1_interval_ms)
        self.level1_pulse_duration = level1_pulse_duration
        self.level1_strength = level1_strength
        self.level3_interval_ms = float(level3_interval_ms)
        self.level3_pulse_duration = level3_pulse_duration
        self.level3_strength = level3_strength
        self.progressive_controller = progressive_controller or ProgressiveVibrationController(
            enabled=True,
            min_interval_ms=250,
            max_interval_ms=3000,
            curve=1.2,
            pulse_duration=1,
            strength=2,
            terminal_feedback_mode="single_pulse",
            direction=direction,
            datarate=datarate,
        )
        self._last_level1_sample = None
        self._last_level3_sample = None

    def reset(self):
        self._last_level1_sample = None
        self._last_level3_sample = None
        if hasattr(self.progressive_controller, "reset"):
            self.progressive_controller.reset()

    def classify_peak(self, peak):
        value = float(peak)
        lower = float(self.ability_range_min_deg)
        upper = float(self.ability_range_max_deg)
        if self.direction == "decreasing":
            value = -value
            lower = -lower
            upper = -upper
        lower, upper = sorted((lower, upper))
        if value < lower:
            return LEVEL_BELOW
        if value >= upper:
            return LEVEL_ABOVE
        return LEVEL_WITHIN

    def update(
        self,
        feedback_level,
        gait_phase_state,
        stance_phase_state,
        swing_phase_state,
        angle,
        training_threshold,
        terminal_threshold,
        sample_index,
        allow_feedback=True,
    ):
        if not self.enabled or not allow_feedback:
            return self._off(REASON_GRADED_DISABLED)

        if feedback_level == LEVEL_BELOW:
            return self._level1(
                gait_phase_state,
                stance_phase_state,
                sample_index,
            )
        if feedback_level == LEVEL_ABOVE:
            return self._level3(
                gait_phase_state,
                swing_phase_state,
                sample_index,
            )
        return self._level2(
            gait_phase_state,
            stance_phase_state,
            angle,
            training_threshold,
            terminal_threshold,
            sample_index,
        )

    def _level1(self, gait_phase_state, stance_phase_state, sample_index):
        if gait_phase_state != GAIT_STANCE or stance_phase_state == STANCE_TOE_OFF:
            return self._off(REASON_LEVEL1_WAITING)
        should_vibrate = self._interval_due(
            sample_index,
            self.level1_interval_ms,
            self._last_level1_sample,
        )
        if should_vibrate:
            self._last_level1_sample = int(sample_index)
        return GradedFeedbackDecision(
            posterior_should_vibrate=should_vibrate,
            front_should_vibrate=False,
            posterior_feedback_state=int(should_vibrate),
            front_feedback_state=FEEDBACK_OFF,
            posterior_duration=self.level1_pulse_duration,
            posterior_strength=self.level1_strength,
            front_duration=0,
            front_strength=0,
            feedback_reason_code=REASON_LEVEL1_STANCE,
            feedback_progress_ratio=0.0,
            feedback_interval_ms=self.level1_interval_ms,
            terminal_goal_met_state=0,
        )

    def _level2(
        self,
        gait_phase_state,
        stance_phase_state,
        angle,
        training_threshold,
        terminal_threshold,
        sample_index,
    ):
        if gait_phase_state != GAIT_STANCE or stance_phase_state not in (
            STANCE_MID,
            STANCE_HEEL_OFF,
            STANCE_TOE_OFF,
        ):
            return self._off(REASON_LEVEL2_WAITING)
        decision = self.progressive_controller.update(
            angle=angle,
            training_threshold=training_threshold,
            terminal_threshold=terminal_threshold,
            sample_index=sample_index,
            allow_feedback=True,
        )
        if hasattr(decision, "posterior_should_vibrate"):
            return decision
        return GradedFeedbackDecision(
            posterior_should_vibrate=decision.should_vibrate,
            front_should_vibrate=False,
            posterior_feedback_state=int(decision.should_vibrate),
            front_feedback_state=FEEDBACK_OFF,
            posterior_duration=decision.pulse_duration,
            posterior_strength=decision.strength,
            front_duration=0,
            front_strength=0,
            feedback_reason_code=REASON_LEVEL2_PROGRESSIVE,
            feedback_progress_ratio=decision.progress_ratio,
            feedback_interval_ms=decision.interval_ms,
            terminal_goal_met_state=int(decision.terminal_goal_met),
        )

    def _level3(self, gait_phase_state, swing_phase_state, sample_index):
        if gait_phase_state != GAIT_SWING:
            return self._off(REASON_LEVEL3_WAITING)
        if swing_phase_state == SWING_DECELERATION:
            return self._off(REASON_LEVEL3_DECELERATION)
        if swing_phase_state not in (SWING_ACCELERATION, SWING_MID):
            return self._off(REASON_LEVEL3_WAITING)
        should_vibrate = self._interval_due(
            sample_index,
            self.level3_interval_ms,
            self._last_level3_sample,
        )
        if should_vibrate:
            self._last_level3_sample = int(sample_index)
        return GradedFeedbackDecision(
            posterior_should_vibrate=False,
            front_should_vibrate=should_vibrate,
            posterior_feedback_state=FEEDBACK_OFF,
            front_feedback_state=int(should_vibrate),
            posterior_duration=0,
            posterior_strength=0,
            front_duration=self.level3_pulse_duration,
            front_strength=self.level3_strength,
            feedback_reason_code=REASON_LEVEL3_SWING,
            feedback_progress_ratio=1.0,
            feedback_interval_ms=self.level3_interval_ms,
            terminal_goal_met_state=1,
        )

    def _interval_due(self, sample_index, interval_ms, last_sample):
        if last_sample is None:
            return True
        interval_samples = max(
            1,
            int(round(float(interval_ms) * self.datarate / 1000.0)),
        )
        return int(sample_index) - int(last_sample) >= interval_samples

    def _off(self, reason_code):
        return GradedFeedbackDecision(
            posterior_should_vibrate=False,
            front_should_vibrate=False,
            posterior_feedback_state=FEEDBACK_OFF,
            front_feedback_state=FEEDBACK_OFF,
            posterior_duration=0,
            posterior_strength=0,
            front_duration=0,
            front_strength=0,
            feedback_reason_code=reason_code,
            feedback_progress_ratio=0.0,
            feedback_interval_ms=0,
            terminal_goal_met_state=0,
        )
