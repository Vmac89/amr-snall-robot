"""Mock-serial tests for the Mission Control server. No hardware required."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from depth_range import front_distance_cm, raw11_to_mm
from kinect_motor import clamp_tilt
from odometry import Odometry
from safety import clamp_for_obstacle
from server import Config, create_app
from video_source import KinectSource


class MissionControlServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.poweroff_calls = []
        self.config = Config(
            mock_serial=True,
            allow_poweroff=False,
            map_path=Path(self.tmp.name) / "robzone_map.json",
            poweroff_fn=self._record_poweroff,
        )
        self.app = create_app(self.config)
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self._stop_app(self.app)
        self.tmp.cleanup()

    def _stop_app(self, app) -> None:
        app.extensions["amr_stop"].set()
        for thread in app.extensions["amr_threads"]:
            thread.join(timeout=1.0)
        app.extensions["amr_bridge"].stop()
        app.extensions["amr_kinect"].close()

    def _record_poweroff(self) -> None:
        self.poweroff_calls.append(True)

    def _data(self) -> dict:
        response = self.client.get("/api/data")
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def _wait(self, predicate, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return False

    def test_index_and_video_and_data(self) -> None:
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"ROBZONE | MISSION CONTROL 11.2", page.data)
        page.close()

        stream = self.client.get("/video_feed", buffered=False)
        self.assertEqual(stream.status_code, 200)
        self.assertIn("multipart/x-mixed-replace", stream.mimetype)
        chunk = b""
        for _ in range(4):
            chunk += next(stream.response)
            if b"\xff\xd8" in chunk:
                break
        stream.close()
        self.assertIn(b"\xff\xd8", chunk)

        self.assertTrue(self._wait(lambda: self._data()["serial_connected"]))
        body = self._data()
        self.assertTrue(body["serial_mock"])
        self.assertIn(body["batt"], ("n/a", "3.30"))
        self.assertFalse(body["batt_calibrated"])
        self.assertEqual(body["dist"], "n/a")
        self.assertFalse(body["dist_calibrated"])
        self.assertFalse(body["kinect_live"])
        self.assertIn("odom", body)
        self.assertFalse(body["odom"]["calibrated"])
        self.assertTrue(body["temp"] == "n/a" or isinstance(body["temp"], (int, float)))

    def test_battery_field_from_mock_telemetry(self) -> None:
        self.assertTrue(self._wait(lambda: self._data()["serial_connected"]))
        self.assertTrue(self._wait(lambda: self._data()["batt"] == "3.30"))
        body = self._data()
        self.assertFalse(body["batt_calibrated"])
        self.assertIsInstance(body["enc_left"], int)

    def test_drive_repeats_while_the_client_refreshes_then_watchdog_coasts(self) -> None:
        self.assertTrue(self._wait(lambda: self._data()["serial_connected"]))
        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline:
            response = self.client.post("/api/cmd?action=DRIVE&left=255&right=-255")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["mapped"], "DRIVE 255 -255")
            time.sleep(0.1)
        moving = self._data()
        self.assertGreater(moving["enc_left"] or 0, 10)
        self.assertLess(moving["enc_right"] or 0, -10)
        self.assertEqual(moving["drive_left"], 255)
        self.assertEqual(moving["drive_right"], -255)
        # /api/data must not refresh the drive watchdog.
        time.sleep(self.config.watchdog_s + 0.45)
        coasted = self._data()
        self.assertEqual(coasted["drive_left"], 0)
        self.assertEqual(coasted["drive_right"], 0)
        self.assertTrue(coasted["safety"]["watchdog_tripped"])
        self.assertFalse(coasted["estop_latched"])
        frozen = coasted["enc_left"]
        time.sleep(0.35)
        self.assertEqual(self._data()["enc_left"], frozen)

    def test_estop_latches_until_reset(self) -> None:
        self.assertTrue(self._wait(lambda: self._data()["serial_connected"]))
        stopped = self.client.post("/api/cmd?action=ESTOP")
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(stopped.get_json()["mapped"], "STOP")
        self.assertTrue(stopped.get_json()["estop_latched"])
        rejected = self.client.post("/api/cmd?action=DRIVE&left=200&right=200")
        self.assertEqual(rejected.status_code, 409)
        self.assertTrue(rejected.get_json()["estop_latched"])
        self.assertEqual(self._data()["drive_left"], 0)
        reset = self.client.post("/api/cmd?action=RESET")
        self.assertEqual(reset.status_code, 200)
        self.assertFalse(self._data()["estop_latched"])
        again = self.client.post("/api/cmd?action=DRIVE&left=200&right=-10")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.get_json()["mapped"], "DRIVE 200 -10")

    def test_drive_rejects_bad_values(self) -> None:
        self.assertTrue(self._wait(lambda: self._data()["serial_connected"]))
        missing = self.client.post("/api/cmd?action=DRIVE&left=10")
        self.assertEqual(missing.status_code, 400)
        huge = self.client.post("/api/cmd?action=DRIVE&left=999&right=0")
        self.assertEqual(huge.status_code, 400)
        unknown = self.client.post("/api/cmd?action=FLY")
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(self._data()["drive_left"], 0)

    def test_tilt_setpoint_without_motor(self) -> None:
        up = self.client.get("/tilt/up")
        self.assertEqual(up.status_code, 200)
        self.assertEqual(up.get_json()["angle"], 5)
        self.assertFalse(up.get_json()["applied"])
        again = self.client.get("/tilt/up")
        self.assertEqual(again.get_json()["angle"], 10)
        down = self.client.get("/tilt/down")
        self.assertEqual(down.get_json()["angle"], 5)
        self.assertEqual(self._data()["tilt_setpoint_deg"], 5)
        missing = self.client.get("/tilt/sideways")
        self.assertEqual(missing.status_code, 404)
        self.assertFalse(hasattr(self.app.extensions["amr_kinect"], "nudge"))
        led = self.client.post("/api/led?value=1")
        self.assertEqual(led.status_code, 200)
        self.assertFalse(led.get_json()["applied"])

    def test_tilt_and_led_use_pyusb(self) -> None:
        class FakeMotor:
            def __init__(self) -> None:
                self.calls = []

            def ctrl_transfer(self, bm_request_type, b_request, w_value, w_index, data):
                self.calls.append((bm_request_type, b_request, w_value, w_index, data))

        fake = FakeMotor()
        motor = self.app.extensions["amr_motor"]
        motor._finder = lambda: fake

        up = self.client.get("/tilt/up")
        self.assertEqual(up.status_code, 200)
        self.assertEqual(up.get_json()["angle"], 5)
        self.assertTrue(up.get_json()["applied"])
        self.assertEqual(fake.calls[-1], (0x40, 0x31, 10, 0, b""))

        for _ in range(7):
            self.client.get("/tilt/up")
        self.assertEqual(motor.angle, 30)
        self.assertEqual(fake.calls[-1], (0x40, 0x31, 60, 0, b""))
        self.assertEqual(self._data()["tilt_setpoint_deg"], 30)

        motor.angle = 0
        down = self.client.get("/tilt/down")
        self.assertEqual(down.get_json()["angle"], -5)
        self.assertTrue(down.get_json()["applied"])
        self.assertEqual(fake.calls[-1], (0x40, 0x31, (-10) & 0xFFFF, 0, b""))

        led = self.client.post("/api/led?value=1")
        self.assertEqual(led.status_code, 200)
        self.assertTrue(led.get_json()["applied"])
        self.assertEqual(led.get_json()["led"], 1)
        self.assertEqual(fake.calls[-1], (0x40, 0x06, 1, 0, b""))

        sent = len(fake.calls)
        bad = self.client.post("/api/led?value=green")
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(bad.get_json()["applied"])
        self.assertEqual(len(fake.calls), sent)

        class Boom:
            def ctrl_transfer(self, *args):
                raise RuntimeError("usb error")

        motor._finder = lambda: Boom()
        failed = self.client.get("/tilt/up")
        self.assertEqual(failed.status_code, 200)
        self.assertFalse(failed.get_json()["applied"])
        self.assertEqual(failed.get_json()["angle"], 0)

    def test_map_round_trip_and_missing_file(self) -> None:
        missing = self.client.get("/api/read_map")
        self.assertEqual(missing.status_code, 404)
        payload = {
            "stations": [{"name": "DOCK", "type": "p", "ip": "10.42.0.50"}],
            "trail": [{"x": 1, "y": 2}],
            "robotPos": {"x": 3, "y": 4, "angle": 0},
            "startPoint": {"x": 3, "y": 4, "angle": 0},
        }
        saved = self.client.post("/api/save_map", json=payload)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.get_json()["status"], "success")
        loaded = self.client.get("/api/read_map")
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(loaded.get_json(), payload)
        rejected = self.client.post(
            "/api/save_map",
            data=json.dumps([1, 2]),
            content_type="application/json",
        )
        self.assertEqual(rejected.status_code, 400)

    def test_poweroff_disabled_does_not_call_shutdown(self) -> None:
        response = self.client.post("/api/poweroff")
        self.assertEqual(response.status_code, 403)
        body = response.get_json()
        self.assertEqual(body["status"], "error")
        self.assertIn("disabled", body["message"])
        self.assertEqual(self.poweroff_calls, [])

    def test_poweroff_armed_uses_injected_runner(self) -> None:
        calls = []

        def runner() -> None:
            calls.append(["shutdown", "-h", "now"])

        config = Config(
            mock_serial=True,
            allow_poweroff=True,
            map_path=Path(self.tmp.name) / "other.json",
            poweroff_fn=runner,
        )
        app = create_app(config)
        try:
            response = app.test_client().post("/api/poweroff")
        finally:
            self._stop_app(app)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "success")
        self.assertEqual(calls, [["shutdown", "-h", "now"]])

    def test_obstacle_stop_blocks_forward_and_allows_reverse(self) -> None:
        self.assertTrue(self._wait(lambda: self._data()["serial_connected"]))
        kinect = self.app.extensions["amr_kinect"]
        kinect.distance_cm = 10.0
        blocked = self.client.post("/api/cmd?action=DRIVE&left=100&right=100")
        self.assertEqual(blocked.status_code, 200)
        self.assertTrue(blocked.get_json()["obstacle_stop"])
        self.assertEqual(blocked.get_json()["mapped"], "STOP")
        self.assertEqual(self._data()["drive_left"], 0)
        backing = self.client.post("/api/cmd?action=DRIVE&left=-40&right=-40")
        self.assertEqual(backing.status_code, 200)
        self.assertEqual(backing.get_json()["mapped"], "DRIVE -40 -40")
        self.assertFalse(backing.get_json()["obstacle_stop"])
        kinect.distance_cm = None
        clear = self.client.post("/api/cmd?action=DRIVE&left=100&right=100")
        self.assertEqual(clear.status_code, 200)
        self.assertEqual(clear.get_json()["mapped"], "DRIVE 100 100")
        self.assertFalse(clear.get_json()["obstacle_stop"])


class GeometryHelpersTest(unittest.TestCase):
    def test_straight_odometry_uses_the_supplied_diameter(self) -> None:
        odom = Odometry(
            wheel_diameter_m=1.0,
            track_width_m=0.2,
            ticks_per_rev=360.0,
            left_sign=1,
            right_sign=1,
            calibrated=False,
        )
        odom.update(0, 0)
        odom.update(360, 360)
        snap = odom.snapshot()
        self.assertAlmostEqual(snap["x"], 3.141592653589793, places=6)
        self.assertAlmostEqual(snap["y"], 0.0, places=6)
        self.assertAlmostEqual(snap["theta"], 0.0, places=6)
        self.assertFalse(snap["calibrated"])

    def test_zero_ticks_per_rev_does_not_move(self) -> None:
        odom = Odometry(ticks_per_rev=0)
        odom.update(0, 0)
        odom.update(100, 100)
        self.assertEqual(odom.snapshot()["x"], 0.0)

    def test_obstacle_clamp(self) -> None:
        self.assertEqual(clamp_for_obstacle(80, 80, None, 40), (80, 80, False))
        self.assertEqual(clamp_for_obstacle(80, 80, 40, 40), (80, 80, False))
        self.assertEqual(clamp_for_obstacle(80, -20, 10, 40), (0, -20, True))
        self.assertEqual(clamp_for_obstacle(-30, -30, 10, 40), (-30, -30, False))

    def test_front_distance_median(self) -> None:
        frame = [[0] * 10 for _ in range(10)]
        for y in range(4, 6):
            for x in range(4, 6):
                frame[y][x] = 1500
        cm, note = front_distance_cm(frame, "mm")
        self.assertEqual(cm, 150.0)
        self.assertEqual(note, "mm")
        empty, why = front_distance_cm(frame, "raw11")
        self.assertIsNone(empty)
        self.assertIn("no valid", why)
        mm = raw11_to_mm(759)
        self.assertIsNotNone(mm)
        self.assertGreater(mm, 200)
        self.assertLess(mm, 8000)

    def test_tilt_clamp(self) -> None:
        self.assertEqual(clamp_tilt(30), 30)
        self.assertEqual(clamp_tilt(31), 30)
        self.assertEqual(clamp_tilt(-30), -30)
        self.assertEqual(clamp_tilt(-40.2), -30)
        self.assertEqual((-60) & 0xFFFF, 65476)

    def test_camera_failure_latches_placeholder(self) -> None:
        calls = {"n": 0}

        class Boom:
            def sync_get_video(self):
                calls["n"] += 1
                raise RuntimeError("Failed to fetch const shift")

            def sync_get_depth(self, format=None):
                calls["n"] += 1
                raise RuntimeError("Failed to fetch const shift")

        src = KinectSource()
        src._freenect = Boom()
        self.assertIsNone(src._capture_once())
        self.assertTrue(src._camera_failed)
        self.assertEqual(src.detail, "Failed to fetch const shift")
        self.assertIsNone(src.distance_cm)
        self.assertEqual(src.jpeg(), src._placeholder)
        self.assertTrue(src.jpeg().startswith(b"\xff\xd8"))
        src._kick_capture()
        src._update_distance()
        self.assertEqual(calls["n"], 1)
        self.assertFalse(src.live)
        self.assertFalse(hasattr(src, "nudge"))
        self.assertFalse(hasattr(src, "_apply_tilt"))


if __name__ == "__main__":
    unittest.main()
