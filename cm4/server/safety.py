"""Server-side motion guards.

The browser (or any other client) must keep posting DRIVE while it wants
the wheels powered. If those posts stop, the motors are coasted. That is
separate from the firmware's own 500 ms command timeout.

ESTOP latches until RESET. A latched stop rejects DRIVE.

Obstacle stop uses a Kinect distance when one exists. With no distance,
forward motion is not blocked: a missing frame is not treated as a range.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from calibration import CLIENT_WATCHDOG_S, OBSTACLE_STOP_CM


class EstopLatched(Exception):
    pass


@dataclass
class Safety:
    watchdog_s: float = CLIENT_WATCHDOG_S
    obstacle_cm: float = OBSTACLE_STOP_CM
    obstacle_calibrated: bool = False
    latched: bool = False
    watchdog_tripped: bool = False
    obstacle_stop: bool = False
    _wants_motion: bool = False
    _last_drive: float = 0.0

    def estop(self) -> None:
        self.latched = True
        self._wants_motion = False
        self.obstacle_stop = False

    def note_coast(self) -> None:
        self._wants_motion = False
        self.obstacle_stop = False

    def reset(self) -> None:
        self.latched = False
        self.watchdog_tripped = False

    def accept_drive(
        self, left: int, right: int, distance_cm: float | None
    ) -> tuple[int, int]:
        if self.latched:
            raise EstopLatched("ESTOP latched; POST action=RESET")
        clamped_left, clamped_right, blocked = clamp_for_obstacle(
            left, right, distance_cm, self.obstacle_cm
        )
        self.obstacle_stop = blocked
        self._wants_motion = clamped_left != 0 or clamped_right != 0
        self._last_drive = time.monotonic()
        if self._wants_motion:
            self.watchdog_tripped = False
        return clamped_left, clamped_right

    def expired(self) -> bool:
        if self.latched or not self._wants_motion:
            return False
        return time.monotonic() - self._last_drive > self.watchdog_s

    def note_watchdog(self) -> None:
        self._wants_motion = False
        self.watchdog_tripped = True
        self.obstacle_stop = False

    def snapshot(self) -> dict:
        return {
            "estop_latched": self.latched,
            "watchdog_tripped": self.watchdog_tripped,
            "watchdog_s": self.watchdog_s,
            "obstacle_stop": self.obstacle_stop,
            "obstacle_threshold_cm": self.obstacle_cm,
            "obstacle_calibrated": self.obstacle_calibrated,
        }


def clamp_for_obstacle(
    left: int, right: int, distance_cm: float | None, threshold_cm: float
) -> tuple[int, int, bool]:
    """Drop forward wheel commands when a real distance is inside the threshold.

    Reverse and zero commands pass through. A turn that still has a positive
    wheel is reduced to the non-positive part so the robot can spin or back
    away. Missing distance does not clamp.
    """
    if distance_cm is None or distance_cm >= threshold_cm:
        return left, right, False
    if left <= 0 and right <= 0:
        return left, right, False
    return min(left, 0), min(right, 0), True
