GAIT_UNKNOWN = 0
GAIT_STANCE = 1
GAIT_SWING = 2

STANCE_NONE = 0
STANCE_HEEL_STRIKE = 1
STANCE_FOOT_FLAT = 2
STANCE_MID = 3
STANCE_HEEL_OFF = 4
STANCE_TOE_OFF = 5

SWING_NONE = 0
SWING_ACCELERATION = 1
SWING_MID = 2
SWING_DECELERATION = 3

LEVEL_UNKNOWN = 0
LEVEL_BELOW = 1
LEVEL_WITHIN = 2
LEVEL_ABOVE = 3


class GaitPhaseState:
    def __init__(
        self,
        gait_cycle_index,
        gait_phase_state,
        stance_phase_state,
        swing_phase_state,
        heel_strike_event_state,
        mid_stance_event_state,
        toe_off_event_state,
        swing_deceleration_state,
        current_cycle_peak_extension,
        previous_cycle_peak_extension,
        previous_cycle_feedback_level,
        current_feedback_level,
    ):
        self.gait_cycle_index = int(gait_cycle_index)
        self.gait_phase_state = int(gait_phase_state)
        self.stance_phase_state = int(stance_phase_state)
        self.swing_phase_state = int(swing_phase_state)
        self.heel_strike_event_state = int(heel_strike_event_state)
        self.mid_stance_event_state = int(mid_stance_event_state)
        self.toe_off_event_state = int(toe_off_event_state)
        self.swing_deceleration_state = int(swing_deceleration_state)
        self.current_cycle_peak_extension = float(current_cycle_peak_extension)
        self.previous_cycle_peak_extension = float(previous_cycle_peak_extension)
        self.previous_cycle_feedback_level = int(previous_cycle_feedback_level)
        self.current_feedback_level = int(current_feedback_level)


class GaitPhaseController:
    def __init__(
        self,
        datarate,
        min_stance_ms,
        min_swing_ms,
        mid_stance_fraction,
        swing_deceleration_fraction,
        ability_range_min_deg,
        ability_range_max_deg,
        direction,
        initial_feedback_level,
    ):
        self.datarate = float(datarate)
        self.min_stance_samples = self._ms_to_samples(min_stance_ms)
        self.min_swing_samples = self._ms_to_samples(min_swing_ms)
        self.mid_stance_fraction = self._clamp_fraction(mid_stance_fraction)
        self.swing_deceleration_fraction = self._clamp_fraction(
            swing_deceleration_fraction
        )
        self.ability_range_min_deg = float(ability_range_min_deg)
        self.ability_range_max_deg = float(ability_range_max_deg)
        self.direction = direction
        self.initial_feedback_level = int(initial_feedback_level)
        if self.initial_feedback_level not in (LEVEL_BELOW, LEVEL_WITHIN, LEVEL_ABOVE):
            self.initial_feedback_level = LEVEL_WITHIN

        self.gait_cycle_index = 0
        self.gait_phase_state = GAIT_UNKNOWN
        self.stance_phase_state = STANCE_NONE
        self.swing_phase_state = SWING_NONE
        self.current_cycle_peak_extension = 0.0
        self.previous_cycle_peak_extension = 0.0
        self.previous_cycle_feedback_level = LEVEL_UNKNOWN
        self.current_feedback_level = self.initial_feedback_level
        self._stance_start_sample = None
        self._swing_start_sample = None
        self._last_stance_duration_samples = self.min_stance_samples

    def update(
        self,
        angle,
        sample_index,
        target_leg_back_state,
        opposite_leg_forward_state=0,
        selected_hip_extending_state=0,
        selected_hip_flexing_state=0,
    ):
        angle = float(angle)
        sample_index = int(sample_index)
        target_leg_back = bool(target_leg_back_state)
        opposite_leg_forward = bool(opposite_leg_forward_state)
        selected_hip_extending = bool(selected_hip_extending_state)
        selected_hip_flexing = bool(selected_hip_flexing_state)

        heel_strike_event = 0
        mid_stance_event = 0
        toe_off_event = 0

        if self.gait_phase_state == GAIT_UNKNOWN:
            if target_leg_back:
                heel_strike_event = self._start_stance(angle, sample_index)
            else:
                self.gait_phase_state = GAIT_SWING
                self.swing_phase_state = SWING_ACCELERATION
                self._swing_start_sample = sample_index
        elif self.gait_phase_state == GAIT_STANCE:
            self._update_peak(angle)
            if self._should_end_stance(
                sample_index,
                target_leg_back,
                selected_hip_flexing,
            ):
                toe_off_event = self._end_stance(sample_index)
            else:
                mid_stance_event = self._update_stance_subphase(
                    sample_index,
                    selected_hip_extending or opposite_leg_forward,
                )
        elif self.gait_phase_state == GAIT_SWING:
            if self._should_start_next_stance(sample_index, target_leg_back):
                heel_strike_event = self._start_stance(angle, sample_index)
            else:
                self._update_swing_subphase(sample_index)

        return self._state(
            heel_strike_event_state=heel_strike_event,
            mid_stance_event_state=mid_stance_event,
            toe_off_event_state=toe_off_event,
        )

    def classify_peak(self, peak):
        value = float(peak)
        lower = float(self.ability_range_min_deg)
        upper = float(self.ability_range_max_deg)
        if self.direction == "decreasing":
            better_value = -value
            lower = -lower
            upper = -upper
        else:
            better_value = value
        lower, upper = sorted((lower, upper))
        if better_value < lower:
            return LEVEL_BELOW
        if better_value >= upper:
            return LEVEL_ABOVE
        return LEVEL_WITHIN

    def _start_stance(self, angle, sample_index):
        self.gait_cycle_index += 1
        self.gait_phase_state = GAIT_STANCE
        self.stance_phase_state = STANCE_HEEL_STRIKE
        self.swing_phase_state = SWING_NONE
        self.current_cycle_peak_extension = float(angle)
        self._stance_start_sample = int(sample_index)
        self._swing_start_sample = None
        return 1

    def _end_stance(self, sample_index):
        self.previous_cycle_peak_extension = self.current_cycle_peak_extension
        self.previous_cycle_feedback_level = self.classify_peak(
            self.previous_cycle_peak_extension
        )
        self.current_feedback_level = self.previous_cycle_feedback_level
        self.gait_phase_state = GAIT_SWING
        self.stance_phase_state = STANCE_TOE_OFF
        self.swing_phase_state = SWING_ACCELERATION
        self._last_stance_duration_samples = max(
            1,
            int(sample_index) - int(self._stance_start_sample or sample_index),
        )
        self._swing_start_sample = int(sample_index)
        self._stance_start_sample = None
        return 1

    def _update_peak(self, angle):
        if self.direction == "decreasing":
            self.current_cycle_peak_extension = min(
                self.current_cycle_peak_extension,
                float(angle),
            )
        else:
            self.current_cycle_peak_extension = max(
                self.current_cycle_peak_extension,
                float(angle),
            )

    def _should_end_stance(
        self,
        sample_index,
        target_leg_back,
        selected_hip_flexing,
    ):
        if self._stance_start_sample is None:
            return False
        stance_elapsed = int(sample_index) - int(self._stance_start_sample)
        if stance_elapsed < self.min_stance_samples:
            return False
        return (not target_leg_back) or selected_hip_flexing

    def _update_stance_subphase(self, sample_index, extension_anchor_active):
        stance_elapsed = int(sample_index) - int(self._stance_start_sample or sample_index)
        mid_stance_samples = max(
            1,
            int(round(self.min_stance_samples * self.mid_stance_fraction)),
        )
        next_state = self.stance_phase_state
        if stance_elapsed >= self.min_stance_samples:
            next_state = STANCE_HEEL_OFF
        elif extension_anchor_active or stance_elapsed >= mid_stance_samples:
            next_state = STANCE_MID
        elif stance_elapsed > 0:
            next_state = STANCE_FOOT_FLAT
        event = int(next_state == STANCE_MID and self.stance_phase_state != STANCE_MID)
        self.stance_phase_state = next_state
        return event

    def _should_start_next_stance(self, sample_index, target_leg_back):
        if not target_leg_back or self._swing_start_sample is None:
            return False
        swing_elapsed = int(sample_index) - int(self._swing_start_sample)
        return swing_elapsed >= self.min_swing_samples

    def _update_swing_subphase(self, sample_index):
        if self._swing_start_sample is None:
            self.swing_phase_state = SWING_ACCELERATION
            return
        swing_elapsed = max(0, int(sample_index) - int(self._swing_start_sample))
        decel_samples = max(
            1,
            int(round(self._last_stance_duration_samples * self.swing_deceleration_fraction)),
        )
        mid_samples = max(1, int(round(decel_samples * 0.5)))
        if swing_elapsed >= decel_samples:
            self.swing_phase_state = SWING_DECELERATION
        elif swing_elapsed >= mid_samples:
            self.swing_phase_state = SWING_MID
        else:
            self.swing_phase_state = SWING_ACCELERATION

    def _state(
        self,
        heel_strike_event_state=0,
        mid_stance_event_state=0,
        toe_off_event_state=0,
    ):
        return GaitPhaseState(
            gait_cycle_index=self.gait_cycle_index,
            gait_phase_state=self.gait_phase_state,
            stance_phase_state=self.stance_phase_state,
            swing_phase_state=self.swing_phase_state,
            heel_strike_event_state=heel_strike_event_state,
            mid_stance_event_state=mid_stance_event_state,
            toe_off_event_state=toe_off_event_state,
            swing_deceleration_state=int(self.swing_phase_state == SWING_DECELERATION),
            current_cycle_peak_extension=self.current_cycle_peak_extension,
            previous_cycle_peak_extension=self.previous_cycle_peak_extension,
            previous_cycle_feedback_level=self.previous_cycle_feedback_level,
            current_feedback_level=self.current_feedback_level,
        )

    def _ms_to_samples(self, value):
        return max(1, int(round(float(value) * self.datarate / 1000.0)))

    def _clamp_fraction(self, value):
        return max(0.0, min(1.0, float(value)))
