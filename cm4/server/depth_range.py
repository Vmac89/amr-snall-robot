"""Front obstacle distance from a Kinect depth frame.

The center window assumes the camera faces the robot's forward direction.
That mount has not been measured. Model string 1505 has not been confirmed
as a libfreenect device. dist_calibrated stays false upstream.

Millimetre frames are used as reported. 11-bit raw frames use the
OpenKinect raw-to-millimetre conversion (the one shipped with libfreenect
examples), which is not a calibration of this sensor:

    mm = 1000 / (raw * -0.0030711016 + 3.3309495161)

Samples outside 0.2 m to 8 m are dropped. That span is the usual Kinect v1
working range quoted with the formula above, not a measurement of this robot.
"""

from __future__ import annotations

_RAW_SLOPE = -0.0030711016
_RAW_INTERCEPT = 3.3309495161
_MIN_MM = 200.0
_MAX_MM = 8000.0


def raw11_to_mm(raw: float) -> float | None:
    if raw <= 0:
        return None
    denom = raw * _RAW_SLOPE + _RAW_INTERCEPT
    if abs(denom) < 1e-9:
        return None
    return 1000.0 / denom


def front_distance_cm(frame, mode: str) -> tuple[float | None, str]:
    """Median of the center 20% of the frame, in centimetres."""
    try:
        height = len(frame)
        if height == 0:
            return None, "empty depth frame"
        width = len(frame[0])
    except (TypeError, IndexError):
        return None, "unreadable depth frame"
    if width == 0:
        return None, "empty depth frame"

    y0 = int(height * 0.4)
    y1 = max(y0 + 1, int(height * 0.6))
    x0 = int(width * 0.4)
    x1 = max(x0 + 1, int(width * 0.6))
    samples: list[float] = []
    for y in range(y0, min(y1, height)):
        row = frame[y]
        for x in range(x0, min(x1, width)):
            mm = _sample_mm(float(row[x]), mode)
            if mm is None or mm < _MIN_MM or mm > _MAX_MM:
                continue
            samples.append(mm)
    if not samples:
        return None, "no valid depth in the center window (" + mode + ")"
    samples.sort()
    median_mm = samples[len(samples) // 2]
    return round(median_mm / 10.0, 1), mode


def _sample_mm(raw: float, mode: str) -> float | None:
    if mode == "mm":
        if raw <= 0:
            return None
        return raw
    if mode == "raw11":
        return raw11_to_mm(raw)
    return None
