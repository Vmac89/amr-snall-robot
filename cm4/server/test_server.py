"""Mock-serial tests for the Mission Control server. No hardware required."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from server import Config, create_app


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
        self.app.extensions["amr_bridge"].stop()
        self.app.extensions["amr_kinect"].close()
        self.tmp.cleanup()

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
        self.assertEqual(body["batt"], "n/a")
        self.assertEqual(body["dist"], "n/a")
        self.assertFalse(body["kinect_live"])
        self.assertTrue(body["temp"] == "n/a" or isinstance(body["temp"], (int, float)))

    def test_drive_heartbeat_and_estop(self) -> None:
        self.assertTrue(self._wait(lambda: self._data()["serial_connected"]))
        response = self.client.post("/api/cmd?action=DRIVE&left=255&right=-255")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["serial"], "OK")
        self.assertEqual(response.get_json()["mapped"], "DRIVE 255 -255")

        def moved() -> bool:
            body = self._data()
            left = body["enc_left"]
            right = body["enc_right"]
            return left is not None and right is not None and left > 0 and right < 0

        self.assertTrue(self._wait(moved), self._data())
        early = self._data()["enc_left"]
        time.sleep(0.7)
        later = self._data()
        self.assertGreaterEqual(later["enc_left"], early + 15)
        self.assertEqual(later["drive_left"], 255)

        stopped = self.client.post("/api/cmd?action=ESTOP")
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(stopped.get_json()["mapped"], "STOP")
        self.assertEqual(stopped.get_json()["serial"], "OK")
        time.sleep(0.35)
        settled = self._data()
        time.sleep(0.45)
        after = self._data()
        self.assertEqual(settled["enc_left"], after["enc_left"])
        self.assertEqual(settled["enc_right"], after["enc_right"])
        self.assertEqual(after["drive_left"], 0)
        self.assertEqual(after["drive_right"], 0)

    def test_drive_rejects_bad_values(self) -> None:
        self.assertTrue(self._wait(lambda: self._data()["serial_connected"]))
        missing = self.client.post("/api/cmd?action=DRIVE&left=10")
        self.assertEqual(missing.status_code, 400)
        huge = self.client.post("/api/cmd?action=DRIVE&left=999&right=0")
        self.assertEqual(huge.status_code, 400)
        unknown = self.client.post("/api/cmd?action=FLY")
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(self._data()["drive_left"], 0)

    def test_tilt_setpoint_without_freenect(self) -> None:
        up = self.client.get("/tilt/up")
        self.assertEqual(up.status_code, 200)
        self.assertEqual(up.get_json()["angle"], 5)
        self.assertFalse(up.get_json()["applied"])
        again = self.client.get("/tilt/up")
        self.assertEqual(again.get_json()["angle"], 10)
        down = self.client.get("/tilt/down")
        self.assertEqual(down.get_json()["angle"], 5)
        missing = self.client.get("/tilt/sideways")
        self.assertEqual(missing.status_code, 404)

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
            app.extensions["amr_bridge"].stop()
            app.extensions["amr_kinect"].close()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "success")
        self.assertEqual(calls, [["shutdown", "-h", "now"]])


if __name__ == "__main__":
    unittest.main()
