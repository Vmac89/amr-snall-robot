"""Kinect MJPEG source with a drawn placeholder when libfreenect is absent.

Model string 1505 has not been identified as a libfreenect device. Tilt uses
libfreenect's own limit (TILT_MAX_DEGREES, 30) only when that library accepts
the call. The angle reported to the page is the commanded setpoint.
"""

from __future__ import annotations

import io
import logging
import threading

from depth_range import front_distance_cm

logger = logging.getLogger("amr.cm4.video")

# libfreenect include/libfreenect.h: #define TILT_MAX_DEGREES 30
TILT_LIMIT_DEG = 30.0
TILT_STEP_DEG = 5.0


def _placeholder_jpeg() -> bytes:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning("Pillow is not installed; video placeholder is a tiny JPEG")
        return _tiny_jpeg()
    image = Image.new("RGB", (640, 360), (8, 8, 8))
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 16, 623, 343), outline=(0, 217, 255))
    draw.text((32, 150), "KINECT OFFLINE", fill=(0, 255, 0))
    draw.text((32, 178), "No libfreenect frame", fill=(0, 180, 180))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def _tiny_jpeg() -> bytes:
    # 1x1 black JPEG, used only when Pillow cannot be imported.
    return bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707"
        "070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c"
        "1c2837292c30313434341f27393d38323c32393432ffc0000b080001000101011100"
        "ffc4001f0000010501010101010100000000000000000102030405060708090a0bff"
        "c400b5100002010303020403050504040000017d0102030004110512213141061351"
        "6107227114328191a1082342b1c11552d1f0243372e182091a161718191a25262728"
        "292a3435363738393a434445464748494a535455565758595a636465666768696a73"
        "7475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2"
        "b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8"
        "e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fb2ad2ffd9"
    )


class KinectSource:
    def __init__(self) -> None:
        self.angle = 0.0
        self.live = False
        self.detail = "not started"
        self.distance_cm: float | None = None
        self.distance_note = "no depth frame"
        self._latest = _placeholder_jpeg()
        self._placeholder = self._latest
        self._freenect = None
        self._import_error: str | None = None
        self._capture: threading.Thread | None = None
        self._tilt: threading.Thread | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="kinect", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def jpeg(self) -> bytes:
        return self._latest

    def nudge(self, direction: str) -> dict:
        delta = TILT_STEP_DEG if direction == "up" else -TILT_STEP_DEG
        self.angle = max(-TILT_LIMIT_DEG, min(TILT_LIMIT_DEG, self.angle + delta))
        applied, detail = self._apply_tilt(self.angle)
        return {"angle": self.angle, "applied": applied, "detail": detail}

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._kick_capture()
            self._stop.wait(0.1 if self.live else 2.0)

    def _load(self):
        if self._import_error is not None:
            return None
        if self._freenect is not None:
            return self._freenect
        try:
            import freenect
        except ImportError as exc:
            self._import_error = str(exc)
            self.detail = "libfreenect is not installed"
            self.live = False
            logger.info("libfreenect is not installed; /video_feed stays on the placeholder")
            return None
        self._freenect = freenect
        return freenect

    def _kick_capture(self) -> None:
        if self._load() is None:
            self._latest = self._placeholder
            return
        if self._capture is not None and self._capture.is_alive():
            return

        def worker() -> None:
            frame = self._capture_once()
            self._update_distance()
            if frame is None:
                self.live = False
                self._latest = self._placeholder
                return
            self._latest = frame
            self.live = True
            self.detail = "libfreenect frame"

        self._capture = threading.Thread(target=worker, name="kinect-grab", daemon=True)
        self._capture.start()

    def _capture_once(self) -> bytes | None:
        freenect = self._freenect
        if freenect is None:
            return None
        try:
            got = freenect.sync_get_video()
        except Exception as exc:
            self.detail = str(exc)
            logger.info("libfreenect video failed: %s", exc)
            return None
        if not got:
            self.detail = "libfreenect returned no frame"
            return None
        frame = got[0]
        try:
            from PIL import Image
        except ImportError:
            self.detail = "Pillow is not installed"
            return None
        try:
            image = Image.fromarray(frame)
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=70)
        except Exception as exc:
            self.detail = str(exc)
            return None
        return buf.getvalue()

    def _update_distance(self) -> None:
        freenect = self._freenect
        if freenect is None:
            self.distance_cm = None
            self.distance_note = self.detail
            return
        mode = "raw11"
        try:
            mm_format = getattr(freenect, "DEPTH_MM", None)
            if mm_format is None:
                got = freenect.sync_get_depth()
            else:
                got = freenect.sync_get_depth(format=mm_format)
                mode = "mm"
        except Exception as exc:
            self.distance_cm = None
            self.distance_note = str(exc)
            return
        if not got:
            self.distance_cm = None
            self.distance_note = "no depth frame"
            return
        cm, note = front_distance_cm(got[0], mode)
        self.distance_cm = cm
        self.distance_note = note

    def _apply_tilt(self, angle: float) -> tuple[bool, str]:
        freenect = self._load()
        if freenect is None:
            return False, self.detail
        if self._tilt is not None and self._tilt.is_alive():
            return False, "previous tilt call has not returned"
        outcome: dict = {}

        def worker() -> None:
            fn = getattr(freenect, "sync_set_tilt_degs", None) or getattr(
                freenect, "set_tilt_degs", None
            )
            if fn is None:
                outcome["error"] = "libfreenect has no tilt function"
                return
            try:
                fn(angle)
            except Exception as exc:
                outcome["error"] = str(exc)
                return
            outcome["ok"] = True

        self._tilt = threading.Thread(target=worker, name="kinect-tilt", daemon=True)
        self._tilt.start()
        self._tilt.join(1.0)
        if self._tilt.is_alive():
            return False, "tilt call timed out"
        if outcome.get("ok"):
            return True, "sent to libfreenect"
        return False, str(outcome.get("error", "tilt was not applied"))
