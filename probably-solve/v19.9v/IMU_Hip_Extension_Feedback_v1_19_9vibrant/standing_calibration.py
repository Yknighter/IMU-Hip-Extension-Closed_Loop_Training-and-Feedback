"""Require a continuous, stable three-IMU pose before setting the hip zero."""
import math


class StandingCalibration:
    SEGMENTS = ("pelvis", "right_thigh", "left_thigh")

    def __init__(self, datarate, duration=2.0, tolerance_deg=2.0, step_deg=0.5):
        values = (datarate, duration, tolerance_deg, step_deg)
        if not all(math.isfinite(float(v)) and float(v) > 0 for v in values):
            raise ValueError("Standing calibration settings must be finite and positive")
        self.datarate = float(datarate)
        self.duration = float(duration)
        self.tolerance_deg = float(tolerance_deg)
        self.step_deg = float(step_deg)
        self.reset_count = 0
        self.reset()

    def reset(self, reason=0):
        # 0: waiting, 1: collecting, 2: movement, 3: complete, 4: interrupted.
        self.state = reason
        if reason in (2, 4):
            self.reset_count += 1
        self.buffers = {name: [] for name in self.SEGMENTS}
        self.start_sample = self.last_sample = self.last_time = None
        self.elapsed = 0.0
        self.deviation_deg = 0.0

    @staticmethod
    def _quat(value):
        q = tuple(float(x) for x in value)
        if len(q) != 4 or not all(math.isfinite(x) for x in q):
            raise ValueError("Invalid quaternion")
        norm = math.sqrt(sum(x * x for x in q))
        if norm < 1e-12:
            raise ValueError("Zero quaternion")
        return tuple(x / norm for x in q)

    @staticmethod
    def _angle(a, b):
        dot = min(1.0, abs(sum(x * y for x, y in zip(a, b))))
        return math.degrees(2.0 * math.acos(dot))

    def update(self, poses, sample, now=None):
        if self.state == 3:
            return True
        try:
            poses = {name: self._quat(poses[name]) for name in self.SEGMENTS}
        except (KeyError, TypeError, ValueError, OverflowError):
            self.reset(4)
            return False
        if self.last_sample is not None and (
                sample != self.last_sample + 1 or
                (now is not None and self.last_time is not None and
                 (now - self.last_time > 0.25 or now < self.last_time))):
            self.reset(4)
        if self.start_sample is not None:
            self.deviation_deg = max(self._angle(poses[k], self.buffers[k][0])
                                     for k in self.SEGMENTS)
            step = max(self._angle(poses[k], self.buffers[k][-1]) for k in self.SEGMENTS)
            if self.deviation_deg > self.tolerance_deg or step > self.step_deg:
                self.reset(2)
        if self.start_sample is None:
            self.start_sample = sample
        for name, quat in poses.items():
            self.buffers[name].append(quat)
        self.last_sample, self.last_time = sample, now
        self.elapsed = min(self.duration, (sample - self.start_sample) / self.datarate)
        if self.elapsed >= self.duration:
            self.state = 3
        elif self.state not in (2, 4) or self.elapsed >= 0.5:
            self.state = 1
        return self.state == 3
