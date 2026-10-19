"""Differential-drive pose from encoder ticks.

Geometry comes from calibration.py. Until those placeholders are replaced
with measurements, snapshot() reports calibrated=False and the pose is only
as good as the placeholders.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass

from calibration import (
    LEFT_TICK_SIGN,
    RIGHT_TICK_SIGN,
    TICKS_PER_REV,
    TRACK_WIDTH_M,
    WHEEL_DIAMETER_M,
)


@dataclass
class Odometry:
    wheel_diameter_m: float = WHEEL_DIAMETER_M
    track_width_m: float = TRACK_WIDTH_M
    ticks_per_rev: float = TICKS_PER_REV
    left_sign: int = LEFT_TICK_SIGN
    right_sign: int = RIGHT_TICK_SIGN
    calibrated: bool = False
    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0
    _prev: tuple[int, int] | None = None
    _lock: threading.Lock = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._lock = threading.Lock()

    def update(self, left_ticks: int, right_ticks: int) -> None:
        with self._lock:
            self._update(left_ticks, right_ticks)

    def _update(self, left_ticks: int, right_ticks: int) -> None:
        if self._prev is None:
            self._prev = (left_ticks, right_ticks)
            return
        prev_l, prev_r = self._prev
        self._prev = (left_ticks, right_ticks)
        if self.ticks_per_rev == 0 or self.track_width_m == 0:
            return
        circumference = math.pi * self.wheel_diameter_m
        left_m = (left_ticks - prev_l) * self.left_sign / self.ticks_per_rev * circumference
        right_m = (right_ticks - prev_r) * self.right_sign / self.ticks_per_rev * circumference
        center = (left_m + right_m) / 2.0
        delta_theta = (right_m - left_m) / self.track_width_m
        mid = self.theta + delta_theta / 2.0
        self.x += center * math.cos(mid)
        self.y += center * math.sin(mid)
        self.theta += delta_theta

    def snapshot(self) -> dict:
        with self._lock:
            return self._snapshot()

    def _snapshot(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "theta": self.theta,
            "calibrated": self.calibrated,
            "wheel_diameter_m": self.wheel_diameter_m,
            "track_width_m": self.track_width_m,
            "ticks_per_rev": self.ticks_per_rev,
            "left_tick_sign": self.left_sign,
            "right_tick_sign": self.right_sign,
        }
