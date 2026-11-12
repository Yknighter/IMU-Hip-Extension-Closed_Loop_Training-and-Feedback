REJECT_NONE = 0
REJECT_TOO_SHORT = 1
REJECT_PEAK_TOO_SMALL = 2


class ExtensionPeakEvent:
    def __init__(
        self,
        peak_deg,
        duration_samples,
        valid_state,
        reject_reason,
        start_sample,
        end_sample,
    ):
        self.peak_deg = float(peak_deg)
        self.duration_samples = int(duration_samples)
        self.valid_state = int(valid_state)
        self.reject_reason = int(reject_reason)
        self.start_sample = int(start_sample)
        self.end_sample = int(end_sample)


class ExtensionPeakCycleTracker:
    def __init__(
        self,
        datarate,
        min_extension_episode_ms=200,
        extension_episode_end_dwell_ms=200,
        min_valid_peak_deg=0.5,
    ):
        self.datarate = float(datarate)
        self.min_episode_samples = self._ms_to_samples(min_extension_episode_ms)
        self.end_dwell_samples = self._ms_to_samples(extension_episode_end_dwell_ms)
        self.min_valid_peak_deg = float(min_valid_peak_deg)
        self.reset()

    def reset(self):
        self.in_episode = False
        self.current_peak_deg = 0.0
        self.current_duration_samples = 0
        self.current_start_sample = 0
        self._end_started_sample = None

    def update(self, extension_deg, sample_index, extension_side_state=None):
        extension = float(extension_deg)
        sample_index = int(sample_index)
        extension_side = (
            extension > 0.0
            if extension_side_state is None
            else bool(extension_side_state)
        )
        if extension_side and extension > 0.0:
            if not self.in_episode:
                self._start_episode(extension, sample_index)
            else:
                self.current_peak_deg = max(self.current_peak_deg, extension)
                self.current_duration_samples += 1
            self._end_started_sample = None
            return None

        if not self.in_episode:
            return None

        if self._end_started_sample is None:
            self._end_started_sample = sample_index
        if sample_index - int(self._end_started_sample) < self.end_dwell_samples:
            return None

        event = self._finish_episode(sample_index)
        self.reset()
        return event

    def _start_episode(self, extension, sample_index):
        self.in_episode = True
        self.current_peak_deg = float(extension)
        self.current_duration_samples = 1
        self.current_start_sample = int(sample_index)
        self._end_started_sample = None

    def _finish_episode(self, sample_index):
        if self.current_duration_samples < self.min_episode_samples:
            valid = 0
            reason = REJECT_TOO_SHORT
        elif self.current_peak_deg < self.min_valid_peak_deg:
            valid = 0
            reason = REJECT_PEAK_TOO_SMALL
        else:
            valid = 1
            reason = REJECT_NONE
        return ExtensionPeakEvent(
            peak_deg=self.current_peak_deg,
            duration_samples=self.current_duration_samples,
            valid_state=valid,
            reject_reason=reason,
            start_sample=self.current_start_sample,
            end_sample=sample_index,
        )

    def _ms_to_samples(self, value):
        return max(1, int(round(float(value) * self.datarate / 1000.0)))
