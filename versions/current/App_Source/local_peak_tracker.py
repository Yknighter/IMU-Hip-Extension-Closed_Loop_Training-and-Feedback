"""Three-sample local maxima, consolidated into extension episodes."""
import math
from dataclasses import dataclass

REJECT_NONE = 0
REJECT_TOO_SHORT = 1
REJECT_PEAK_TOO_SMALL = 2
REJECT_NO_LOCAL_PEAK = 3


@dataclass
class LocalPeak:
    peak_deg: float
    peak_sample: int
    confirmed_sample: int


class LocalPeakDetector:
    """Compare a middle sample with its left and right neighbours.

    Flat tops are merged, requiring a rise into and a fall out of the plateau.
    """
    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = None
        self.previous_sample = None
        self.plateau_start = None
        self.risen = False

    def update(self, value, sample_index):
        value = float(value)
        sample = int(sample_index)
        if not math.isfinite(value):
            self.reset()
            return None
        peak = None
        if self.previous is None:
            self.plateau_start = sample
        elif value > self.previous:
            self.risen = True
            self.plateau_start = sample
        elif value < self.previous:
            if self.risen:
                peak = LocalPeak(self.previous,
                                 (self.plateau_start + self.previous_sample) // 2,
                                 sample)
            self.risen = False
            self.plateau_start = sample
        self.previous = value
        self.previous_sample = sample
        return peak


@dataclass
class ExtensionPeakEvent:
    peak_deg: float
    duration_samples: int
    valid_state: int
    reject_reason: int
    start_sample: int
    end_sample: int
    peak_sample: int = -1
    candidate_count: int = 0


class ExtensionPeakCycleTracker:
    def __init__(self, datarate, min_extension_episode_ms=200,
                 extension_episode_end_dwell_ms=200, min_valid_peak_deg=0.5):
        self.datarate = float(datarate)
        self.min_episode_samples = self._ms_to_samples(min_extension_episode_ms)
        self.end_dwell_samples = self._ms_to_samples(extension_episode_end_dwell_ms)
        self.min_valid_peak_deg = float(min_valid_peak_deg)
        self.detector = LocalPeakDetector()
        self.reset()

    def _clear_episode(self):
        self.in_episode = False
        self.current_peak_deg = 0.0
        self.current_peak_sample = -1
        self.current_duration_samples = 0
        self.current_start_sample = 0
        self.candidate_count = 0
        self._end_started_sample = None

    def reset(self):
        self.detector.reset()
        self.local_peak_event = None
        self._clear_episode()

    def update(self, extension_deg, sample_index, extension_side_state=None):
        extension = float(extension_deg)
        sample = int(sample_index)
        self.local_peak_event = None
        if not math.isfinite(extension):
            self.reset()
            return None
        extension_side = extension > 0.0 and (
            extension_side_state is None or bool(extension_side_state))
        if extension_side and not self.in_episode:
            self.in_episode = True
            self.current_start_sample = sample
        candidate = self.detector.update(extension, sample)
        if (candidate is not None and self.in_episode and candidate.peak_deg > 0.0
                and candidate.peak_sample >= self.current_start_sample):
            self.local_peak_event = candidate
            self.candidate_count += 1
            if candidate.peak_deg > self.current_peak_deg:
                self.current_peak_deg = candidate.peak_deg
                self.current_peak_sample = candidate.peak_sample
        if extension_side:
            self.current_duration_samples += 1
            self._end_started_sample = None
            return None
        if not self.in_episode:
            return None
        if self._end_started_sample is None:
            self._end_started_sample = sample
        if sample - self._end_started_sample < self.end_dwell_samples:
            return None
        reason = REJECT_NONE
        if self.current_duration_samples < self.min_episode_samples:
            reason = REJECT_TOO_SHORT
        elif not self.candidate_count:
            reason = REJECT_NO_LOCAL_PEAK
        elif self.current_peak_deg < self.min_valid_peak_deg:
            reason = REJECT_PEAK_TOO_SMALL
        event = ExtensionPeakEvent(
            self.current_peak_deg, self.current_duration_samples,
            int(reason == REJECT_NONE), reason, self.current_start_sample,
            sample, self.current_peak_sample, self.candidate_count)
        self._clear_episode()
        return event

    def _ms_to_samples(self, value):
        return max(1, int(round(float(value) * self.datarate / 1000.0)))
