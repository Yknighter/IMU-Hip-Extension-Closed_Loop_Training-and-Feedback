"""Reject discontinuous or delayed frames before feedback consumes them.

Sampletime is a 16-bit millisecond clock, as used by vibration_measurement.
Lag is additional queue delay relative to the first received frame, not an
absolute sensor-to-Hub latency measurement. Never re-anchor it after a gap.
"""
import math

OK = 0
INVALID_CLOCK = 1
DUPLICATE = 2
CLOCK_REVERSED = 3
SAMPLE_GAP = 4
PACKAGE_GAP = 5
STALE = 6
RECEIVE_TIMEOUT = 7
INVALID_POSE = 8


class FrameGuard:
    def __init__(self, datarate, node_count, max_period_factor=1.5,
                 max_lag_sec=0.05, receive_timeout_sec=0.1):
        settings = (datarate, max_period_factor, max_lag_sec, receive_timeout_sec)
        if not all(math.isfinite(float(x)) and float(x) > 0 for x in settings):
            raise ValueError("Frame guard timing must be finite and positive")
        if max_period_factor <= 1 or node_count <= 0:
            raise ValueError("Invalid frame guard settings")
        self.period = 1.0 / float(datarate)
        self.max_period = self.period * float(max_period_factor)
        self.max_lag = float(max_lag_sec)
        self.receive_timeout = float(receive_timeout_sec)
        self.node_count = int(node_count)
        self.reset()

    def reset(self):
        self.clocks = [None] * self.node_count
        self.last_receive = None
        self.sample_time_sec = 0.0
        self.fresh = False
        self.clock_fault = False
        self.interrupted = False
        self.gap_event = self.gap_count = self.reason = 0
        self.gap_duration = self.lag = self.receive_interval = 0.0

    def reject(self, reason, duration=0.0):
        if not self.interrupted:
            self.gap_event = 1
            self.gap_count += 1
        self.interrupted = True
        self.fresh = False
        self.reason = int(reason)
        self.gap_duration = max(0.0, float(duration))
        return False

    @staticmethod
    def _clock(node):
        tick = float(node["Sampletime"])
        package = float(node["Package"])
        if (not math.isfinite(tick) or not 0 <= tick < 65536 or
                not math.isfinite(package) or package < 0 or not package.is_integer()):
            raise ValueError("Invalid sensor clock")
        return tick, int(package)

    def observe(self, data, now, commit=True):
        now = float(now)
        self.gap_event = 0
        if not math.isfinite(now):
            return self.reject(INVALID_CLOCK)
        self.receive_interval = (0.0 if self.last_receive is None
                                 else now - self.last_receive)
        if self.receive_interval < 0 or self.receive_interval >= 32.768:
            # Beyond half a hardware-clock cycle, wrap count is ambiguous.
            self.clock_fault = True
        self.last_receive = now
        if self.clock_fault:
            return self.reject(CLOCK_REVERSED)
        reason = OK
        duration = 0.0
        if self.receive_interval > self.receive_timeout:
            reason = RECEIVE_TIMEOUT
            duration = self.receive_interval
        was_fresh = self.fresh
        try:
            if len(data) != self.node_count:
                raise ValueError("Incomplete frame")
            values = [self._clock(node) for node in data]
        except (TypeError, KeyError, ValueError, OverflowError):
            return self.reject(INVALID_CLOCK)
        lags, elapsed_times = [], []
        for index, (tick, package) in enumerate(values):
            old = self.clocks[index]
            if old is None:
                elapsed, offset = 0.0, now
            else:
                previous_tick, previous_package, elapsed, offset = old
                delta_ms = (tick - previous_tick) % 65536.0
                if delta_ms == 0:
                    reason = reason or DUPLICATE
                    lags.append(max(0.0, now - (offset + elapsed)))
                    elapsed_times.append(elapsed)
                    continue
                if delta_ms >= 32768:
                    self.clock_fault = True
                    return self.reject(CLOCK_REVERSED)
                delta = delta_ms / 1000.0
                if delta > self.max_period + 1e-9:
                    reason = reason or SAMPLE_GAP
                    duration = max(duration, delta - self.period)
                # The package counter width is not documented. An exact wrap
                # to zero is accepted only alongside a continuous sensor clock.
                if package != previous_package + 1 and package != 0:
                    reason = reason or PACKAGE_GAP
                elif package == previous_package:
                    reason = reason or DUPLICATE
                elapsed += delta
                # Allow at most 200 ppm of positive clock drift while healthy.
                # During interruption the baseline is frozen, so old buffered
                # packets cannot redefine themselves as current data.
                drift = (min(max(self.receive_interval, 0.0), self.period * 2)
                         * 0.0002 if was_fresh and reason == OK else 0.0)
                offset = min(offset + drift, now - elapsed)
            lag = max(0.0, now - (offset + elapsed))
            lags.append(lag)
            elapsed_times.append(elapsed)
            self.clocks[index] = (tick, package, elapsed, offset)
        self.lag = max(lags, default=0.0)
        self.sample_time_sec = min(elapsed_times, default=0.0)
        if self.lag > self.max_lag + 1e-9:
            reason = reason or STALE
            duration = max(duration, self.lag)
        if reason:
            return self.reject(reason, duration)
        self.fresh = True
        if commit:
            self.accept()
        self.reason = OK
        return True

    def accept(self):
        """Commit a frame after its pose and control-stage checks also passed."""
        self.interrupted = False

    def can_actuate(self, now):
        # Recheck at the actual command boundary, after computation and I/O.
        return (self.fresh and self.last_receive is not None and
                0 <= float(now) - self.last_receive and
                self.lag + float(now) - self.last_receive <= self.max_lag + 1e-9)

    def metrics(self):
        return {
            "data_fresh_state": int(self.fresh),
            "data_gap_event": int(self.gap_event),
            "data_gap_count": int(self.gap_count),
            "data_gap_reason": int(self.reason),
            "data_gap_duration_sec": float(self.gap_duration),
            "data_lag_sec": float(self.lag),
            "data_receive_interval_sec": float(self.receive_interval),
        }
