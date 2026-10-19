"""USB motor and LED control for the Kinect 1414, independent of the camera.

The motor is USB 045e:02b0. On this CM4, libfreenect's camera path fails
with "Failed to fetch const shift", and freenect.open_device followed by a
tilt call segfaults. These two control transfers were tested on the device
and do not go through libfreenect:

    ctrl_transfer(0x40, 0x31, (deg * 2) & 0xFFFF, 0, b'')  # tilt, deg in -30..30
    ctrl_transfer(0x40, 0x06, led, 0, b'')                 # LED; 1 is green

python3-usb (the usb module) is an apt package. 51-kinect.rules allows
non-root access to 045e:02b0.
"""

from __future__ import annotations

import threading

VENDOR_ID = 0x045E
PRODUCT_ID = 0x02B0
REQ_TYPE_OUT = 0x40
REQ_TILT = 0x31
REQ_LED = 0x06
TILT_LIMIT_DEG = 30
TILT_STEP_DEG = 5


def clamp_tilt(degrees: float) -> int:
    return max(-TILT_LIMIT_DEG, min(TILT_LIMIT_DEG, int(round(degrees))))


def _default_finder():
    try:
        import usb.core
    except ImportError as exc:
        raise LookupError("python3-usb is not installed") from exc
    try:
        device = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    except Exception as exc:
        raise LookupError(str(exc)) from exc
    if device is None:
        raise LookupError("Kinect motor 045e:02b0 not found")
    return device


class KinectMotor:
    def __init__(self, finder=None) -> None:
        self.angle = 0
        self.detail = "not commanded"
        self._finder = finder or _default_finder
        self._lock = threading.RLock()

    def nudge(self, direction: str) -> dict:
        with self._lock:
            delta = TILT_STEP_DEG if direction == "up" else -TILT_STEP_DEG
            return self.set_tilt(self.angle + delta)

    def set_tilt(self, degrees: float) -> dict:
        clamped = clamp_tilt(degrees)
        with self._lock:
            self.angle = clamped
            device, detail = self._open()
            if device is None:
                self.detail = detail
                return {"angle": self.angle, "applied": False, "detail": detail}
            wvalue = (clamped * 2) & 0xFFFF
            try:
                device.ctrl_transfer(REQ_TYPE_OUT, REQ_TILT, wvalue, 0, b"")
            except Exception as exc:
                self.detail = str(exc)
                return {"angle": self.angle, "applied": False, "detail": self.detail}
            self.detail = "tilt sent"
            return {"angle": self.angle, "applied": True, "detail": self.detail}

    def set_led(self, code: int) -> dict:
        with self._lock:
            device, detail = self._open()
            if device is None:
                self.detail = detail
                return {"led": code, "applied": False, "detail": detail}
            try:
                device.ctrl_transfer(REQ_TYPE_OUT, REQ_LED, code, 0, b"")
            except Exception as exc:
                self.detail = str(exc)
                return {"led": code, "applied": False, "detail": self.detail}
            self.detail = "led sent"
            return {"led": code, "applied": True, "detail": self.detail}

    def _open(self):
        try:
            device = self._finder()
        except LookupError as exc:
            return None, str(exc)
        except Exception as exc:
            return None, str(exc)
        if device is None:
            return None, "Kinect motor 045e:02b0 not found"
        return device, ""
