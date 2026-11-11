"""One fixed short pulse per qualifying extension."""
import math
from dataclasses import dataclass

PULSE_NONE = 0
PULSE_REWARD = 1
MAX_REWARD_PULSE_DURATION_SEC = 0.25


def validate_vibration_strength(value):
    """Reject unsupported values before sending a vibration command."""
    message = "Vibration strength must be an integer from 1 to 4"
    if isinstance(value, bool):
        raise ValueError(message)
    try:
        strength = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(message) from None
    if not math.isfinite(strength) or not strength.is_integer() or not 1 <= strength <= 4:
        raise ValueError(message)
    return int(strength)


@dataclass
class RewardDecision:
    stop: bool = False
    pulse_kind: int = PULSE_NONE
    duration: float = 0.0
    strength: int = 0
    qualified: bool = False
    suppressed: bool = False


class RewardFeedbackController:
    def __init__(self, datarate, target_dwell_ms=30, rearm_ms=200,
                 duration=0.2, strength=2):
        values = (datarate, target_dwell_ms, rearm_ms, duration)
        if not all(math.isfinite(float(v)) for v in values):
            raise ValueError("Reward timing must be finite")
        if datarate <= 0 or duration <= 0:
            raise ValueError("Sample rate and pulse durations must be positive")
        if min(target_dwell_ms, rearm_ms) < 0:
            raise ValueError("Reward dwell and rearm time must be non-negative")
        self.strength = validate_vibration_strength(strength)
        self.datarate = float(datarate)
        self.dwell_samples = self._samples(target_dwell_ms / 1000.0)
        self.rearm_samples = self._samples(rearm_ms / 1000.0)
        # Enforce a hard software limit even when an older Hub config requests
        # a longer pulse. The reward stays latched for this extension cycle.
        self.duration = min(float(duration), MAX_REWARD_PULSE_DURATION_SEC)
        self.qualified_count = 0
        self.reward_count = 0
        self.level_up_count = 0  # Legacy exported field; upgrades never vibrate.
        self.suppressed_count = 0
        self.cycle_index = 0
        self.reset()

    def _samples(self, seconds):
        return max(0, int(math.ceil(float(seconds) * self.datarate - 1e-9)))

    def reset(self):
        """Cancel active feedback; retain session counters."""
        self.armed = False
        self.in_cycle = False
        self.cycle_qualified = False
        self.cycle_target = 0.0
        self.neutral_since = None
        self.target_since = None
        self.active_kind = PULSE_NONE
        self.active_until = None
        self.pending_level_up = False  # Legacy exported field; never queued.
        self.last_sample = None
        self.last_time = None

    def _start_pulse(self, decision, timestamp):
        self.active_kind = PULSE_REWARD
        self.active_until = timestamp + self.duration
        decision.pulse_kind = PULSE_REWARD
        decision.duration = self.duration
        decision.strength = self.strength
        self.reward_count += 1

    def update(self, extension, target, sample_index, level_up=False, sample_time_sec=None):
        # Accept legacy callers' level_up flag, but it has no effect on vibration.
        sample = int(sample_index)
        timestamp = sample / self.datarate if sample_time_sec is None else float(sample_time_sec)
        decision = RewardDecision()
        if (not math.isfinite(float(extension)) or not math.isfinite(float(target))
                or not math.isfinite(timestamp) or target <= 0
                or (self.last_sample is not None and sample <= self.last_sample)
                or (self.last_time is not None and timestamp <= self.last_time)):
            decision.stop = True
            self.reset()
            return decision
        self.last_sample = sample
        self.last_time = timestamp
        if self.active_until is not None and timestamp + 1e-9 >= self.active_until:
            decision.stop = True
            self.active_kind = PULSE_NONE
            self.active_until = None
        if extension <= 0.0:
            self.target_since = None
            if self.neutral_since is None:
                self.neutral_since = timestamp
            if timestamp - self.neutral_since + 1e-9 >= self.rearm_samples / self.datarate:
                self.armed = True
                self.in_cycle = False
                self.cycle_qualified = False
        else:
            self.neutral_since = None
            if self.armed and not self.in_cycle:
                self.in_cycle = True
                self.armed = False
                self.cycle_target = float(target)
                self.cycle_index += 1
            if self.in_cycle and not self.cycle_qualified:
                if extension >= self.cycle_target:
                    if self.target_since is None:
                        self.target_since = timestamp
                    if timestamp - self.target_since + 1e-9 >= self.dwell_samples / self.datarate:
                        self.cycle_qualified = True
                        self.qualified_count += 1
                        decision.qualified = True
                else:
                    self.target_since = None
        if decision.qualified:
            if self.active_kind != PULSE_NONE:
                decision.suppressed = True
                self.suppressed_count += 1
            else:
                self._start_pulse(decision, timestamp)
        return decision
