try:
    from .gait_phase_controller import (
        GAIT_STANCE,
        STANCE_HEEL_OFF,
        STANCE_MID,
        STANCE_TOE_OFF,
    )
    from .progressive_vibration import ProgressiveVibrationController
except ImportError:
    from gait_phase_controller import (
        GAIT_STANCE,
        STANCE_HEEL_OFF,
        STANCE_MID,
        STANCE_TOE_OFF,
    )
    from progressive_vibration import ProgressiveVibrationController

FEEDBACK_OFF = 0
FEEDBACK_ON = 1

LEVEL_UNKNOWN = 0
LEVEL_BELOW = 1
LEVEL_WITHIN = 2
LEVEL_ABOVE = 3

REASON_DISABLED = 30
REASON_LEVEL1_BELOW_ABILITY = 31
REASON_LEVEL2_PROGRESSIVE = 32
REASON_LEVEL3_WAITING_LIMIT = 33
REASON_LEVEL3_FRONT_BURST = 34
REASON_LEVEL3_BURST_DONE = 35
REASON_LEVEL3_WAITING_EXTENSION = 36


class AngleGradedFeedbackDecision:
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
        angle_feedback_level,
        angle_limit_burst_count,
        angle_limit_burst_remaining,
        angle_limit_latched_state,
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
        self.angle_feedback_level = int(angle_feedback_level)
        self.angle_limit_burst_count = int(angle_limit_burst_count)
        self.angle_limit_burst_remaining = int(angle_limit_burst_remaining)
        self.angle_limit_latched_state = int(angle_limit_latched_state)


class AngleGradedFeedbackStrategy:
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
        front_pulse_count,
        front_pulse_interval_ms,
        front_pulse_duration,
        front_strength,
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
        self.front_pulse_count = max(1, int(front_pulse_count))
        self.front_pulse_interval_ms = float(front_pulse_interval_ms)
        self.front_pulse_duration = front_pulse_duration
        self.front_strength = front_strength
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
        self._burst_remaining = 0
        self._threshold_latched = False

    def reset(self):
        self._last_level1_sample = None
        self._burst_remaining = 0
        self._threshold_latched = False
        if hasattr(self.progressive_controller, "reset"):
            self.progressive_controller.reset()

    def update(
        self,
        angle,
        feedback_level,
        gait_phase_state,
        stance_phase_state,
        hip_extending_state,
        target_phase_state,
        training_threshold,
        terminal_threshold,
        sample_index,
        allow_feedback=True,
    ):
        if not self.enabled or not allow_feedback:
            return self._off(REASON_DISABLED, LEVEL_UNKNOWN)

        level = (
            LEVEL_ABOVE
            if self._meets_or_exceeds(angle, training_threshold)
            else int(feedback_level)
        )
        threshold_met = self._meets_or_exceeds(angle, training_threshold)
        if not threshold_met:
            self._threshold_latched = False
            self._burst_remaining = 0

        if level == LEVEL_BELOW:
            return self._level1(gait_phase_state, stance_phase_state, sample_index)
        if level == LEVEL_WITHIN:
            return self._level2(
                gait_phase_state,
                stance_phase_state,
                angle,
                training_threshold,
                terminal_threshold,
                sample_index,
            )
        return self._level3(
            bool(hip_extending_state),
            bool(target_phase_state),
            threshold_met,
        )

    def classify_angle(self, angle, training_threshold):
        if self._meets_or_exceeds(angle, training_threshold):
            return LEVEL_ABOVE
        if self._below_ability_min(angle):
            return LEVEL_BELOW
        return LEVEL_WITHIN

    def _level1(self, gait_phase_state, stance_phase_state, sample_index):
        if gait_phase_state != GAIT_STANCE or stance_phase_state == STANCE_TOE_OFF:
            return self._off(REASON_LEVEL1_BELOW_ABILITY, LEVEL_BELOW)
        should_vibrate = self._interval_due(
            sample_index,
            self.level1_interval_ms,
            self._last_level1_sample,
        )
        if should_vibrate:
            self._last_level1_sample = int(sample_index)
        return AngleGradedFeedbackDecision(
            posterior_should_vibrate=should_vibrate,
            front_should_vibrate=False,
            posterior_feedback_state=int(should_vibrate),
            front_feedback_state=FEEDBACK_OFF,
            posterior_duration=self.level1_pulse_duration,
            posterior_strength=self.level1_strength,
            front_duration=0,
            front_strength=0,
            feedback_reason_code=REASON_LEVEL1_BELOW_ABILITY,
            feedback_progress_ratio=0.0,
            feedback_interval_ms=self.level1_interval_ms,
            terminal_goal_met_state=0,
            angle_feedback_level=LEVEL_BELOW,
            angle_limit_burst_count=0,
            angle_limit_burst_remaining=0,
            angle_limit_latched_state=int(self._threshold_latched),
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
            return self._off(REASON_LEVEL2_PROGRESSIVE, LEVEL_WITHIN)
        decision = self.progressive_controller.update(
            angle=angle,
            training_threshold=training_threshold,
            terminal_threshold=terminal_threshold,
            sample_index=sample_index,
            allow_feedback=True,
        )
        if hasattr(decision, "posterior_should_vibrate"):
            return decision
        return AngleGradedFeedbackDecision(
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
            angle_feedback_level=LEVEL_WITHIN,
            angle_limit_burst_count=0,
            angle_limit_burst_remaining=0,
            angle_limit_latched_state=int(self._threshold_latched),
        )

    def _level3(self, hip_extending_state, target_phase_state, threshold_met):
        should_front = bool(threshold_met) and not self._threshold_latched
        if should_front:
            self._threshold_latched = True

        if should_front:
            reason = REASON_LEVEL3_FRONT_BURST
        elif self._threshold_latched:
            reason = REASON_LEVEL3_BURST_DONE
        else:
            reason = REASON_LEVEL3_WAITING_LIMIT

        return AngleGradedFeedbackDecision(
            posterior_should_vibrate=False,
            front_should_vibrate=should_front,
            posterior_feedback_state=FEEDBACK_OFF,
            front_feedback_state=int(should_front),
            posterior_duration=0,
            posterior_strength=0,
            front_duration=self.front_pulse_duration,
            front_strength=self.front_strength,
            feedback_reason_code=reason,
            feedback_progress_ratio=1.0 if threshold_met else 0.0,
            feedback_interval_ms=self.front_pulse_interval_ms,
            terminal_goal_met_state=int(threshold_met),
            angle_feedback_level=LEVEL_ABOVE,
            angle_limit_burst_count=1 if self._threshold_latched else 0,
            angle_limit_burst_remaining=0,
            angle_limit_latched_state=int(self._threshold_latched),
        )

    def _below_ability_min(self, angle):
        if self.direction == "decreasing":
            return float(angle) > float(self.ability_range_min_deg)
        return float(angle) < float(self.ability_range_min_deg)

    def _meets_or_exceeds(self, angle, threshold):
        if self.direction == "decreasing":
            return float(angle) <= float(threshold)
        return float(angle) >= float(threshold)

    def _interval_due(self, sample_index, interval_ms, last_sample):
        if last_sample is None:
            return True
        interval_samples = max(
            1,
            int(round(float(interval_ms) * self.datarate / 1000.0)),
        )
        return int(sample_index) - int(last_sample) >= interval_samples

    def _off(self, reason_code, level):
        return AngleGradedFeedbackDecision(
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
            angle_feedback_level=level,
            angle_limit_burst_count=0,
            angle_limit_burst_remaining=self._burst_remaining,
            angle_limit_latched_state=int(self._threshold_latched),
        )
