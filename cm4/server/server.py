"""Mission Control HTTP server for the Raspberry Pi CM4.

Serves web/mission-control/index.html and the routes that page calls.
Wheel commands go out as ESP32 serial DRIVE / STOP lines. Encoder samples
from ENC / TELEM come back on /api/data. There is no wheel-geometry math
in this process.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from serial_bridge import WHEEL_MAX, WHEEL_MIN, SerialBridge, SerialPort, MockEsp32
from video_source import KinectSource

logger = logging.getLogger("amr.cm4")

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE_DIR = REPO_ROOT / "web" / "mission-control"
DEFAULT_MAP = Path(__file__).resolve().parent / "data" / "robzone_map.json"
MAX_MAP_BYTES = 1_000_000


@dataclass
class Config:
    host: str = "0.0.0.0"
    port: int = 8080
    serial_port: str = "/dev/ttyAMA0"
    baud: int = 115200
    mock_serial: bool = False
    allow_poweroff: bool = False
    map_path: Path = DEFAULT_MAP
    poweroff_fn: object | None = None


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def config_from_env() -> Config:
    map_env = os.environ.get("AMR_MAP_PATH", "").strip()
    return Config(
        host=os.environ.get("AMR_HOST", "0.0.0.0"),
        port=int(os.environ.get("AMR_PORT", "8080")),
        serial_port=os.environ.get("AMR_SERIAL_PORT", "/dev/ttyAMA0"),
        baud=int(os.environ.get("AMR_SERIAL_BAUD", "115200")),
        mock_serial=_env_flag("AMR_MOCK_SERIAL"),
        allow_poweroff=_env_flag("AMR_ALLOW_POWEROFF"),
        map_path=Path(map_env) if map_env else DEFAULT_MAP,
    )


def default_poweroff() -> None:
    completed = subprocess.run(
        ["shutdown", "-h", "now"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "shutdown failed").strip()
        raise RuntimeError(detail)


def cpu_temp_c() -> float | None:
    """Linux thermal zone, millidegrees. Not a battery or motor reading."""
    path = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        raw = int(path.read_text().strip())
    except (OSError, ValueError):
        return None
    return raw / 1000.0


def create_app(config: Config) -> Flask:
    app = Flask(__name__)
    if config.mock_serial:
        bridge = SerialBridge(port_factory=MockEsp32, mock=True)
    else:
        bridge = SerialBridge(
            port_factory=lambda: SerialPort(config.serial_port, config.baud),
            mock=False,
        )
    kinect = KinectSource()
    bridge.start()
    kinect.start()
    app.extensions["amr_bridge"] = bridge
    app.extensions["amr_kinect"] = kinect
    app.extensions["amr_config"] = config

    @app.get("/")
    def index():
        return send_from_directory(PAGE_DIR, "index.html")

    @app.get("/video_feed")
    def video_feed():
        def generate():
            try:
                while True:
                    frame = kinect.jpeg()
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(frame)).encode("ascii") + b"\r\n\r\n"
                        + frame
                        + b"\r\n"
                    )
                    time.sleep(0.1)
            except GeneratorExit:
                return

        return Response(
            generate(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.get("/api/data")
    def api_data():
        body = bridge.snapshot()
        # No pack voltage or range sensor is on the serial protocol. A truthy
        # token keeps the page from substituting its own 12.4 V / 0 cm text.
        # temp is the CPU thermal zone when that sysfs file exists.
        temp = cpu_temp_c()
        body["temp"] = temp if temp is not None else "n/a"
        body["batt"] = "n/a"
        body["dist"] = "n/a"
        body["kinect_live"] = kinect.live
        body["tilt_setpoint_deg"] = kinect.angle
        return jsonify(body)

    @app.get("/tilt/<direction>")
    def tilt(direction: str):
        if direction not in ("up", "down"):
            return jsonify(status="error", message="unknown tilt direction"), 404
        return jsonify(kinect.nudge(direction))

    @app.post("/api/cmd")
    def api_cmd():
        action = request.args.get("action", "").strip()
        try:
            if action in ("ESTOP", "STOP"):
                serial_line = bridge.estop()
                mapped = "STOP"
            elif action == "PING":
                serial_line = bridge.ping()
                mapped = "PING"
            elif action == "DRIVE":
                left = _wheel_param("left")
                right = _wheel_param("right")
                if left is None or right is None:
                    return (
                        jsonify(
                            status="error",
                            message="DRIVE needs integer left and right query parameters",
                        ),
                        400,
                    )
                if (
                    left < WHEEL_MIN
                    or left > WHEEL_MAX
                    or right < WHEEL_MIN
                    or right > WHEEL_MAX
                ):
                    return (
                        jsonify(
                            status="error",
                            message=f"wheel command out of range {WHEEL_MIN}..{WHEEL_MAX}",
                        ),
                        400,
                    )
                serial_line = bridge.drive(left, right)
                mapped = f"DRIVE {left} {right}"
            else:
                return (
                    jsonify(
                        status="error",
                        message="unsupported action; use ESTOP, STOP, DRIVE, or PING",
                    ),
                    400,
                )
        except ConnectionError as exc:
            return jsonify(status="error", message=str(exc)), 503
        except TimeoutError:
            return jsonify(status="error", message="ESP32 did not answer"), 504
        status = "ok" if serial_line in ("OK", "PONG") else "error"
        code = 200 if status == "ok" else 502
        return (
            jsonify(status=status, action=action, mapped=mapped, serial=serial_line),
            code,
        )

    @app.post("/api/save_map")
    def save_map():
        if request.content_length is not None and request.content_length > MAX_MAP_BYTES:
            return jsonify(status="error", message="map body is too large"), 413
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(status="error", message="JSON object required"), 400
        path = config.map_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(path)
        return jsonify(status="success")

    @app.get("/api/read_map")
    def read_map():
        path = config.map_path
        if not path.is_file():
            return jsonify(status="error", message="No file profile saved yet."), 404
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            return jsonify(status="error", message=str(exc)), 500
        return jsonify(payload)

    @app.post("/api/poweroff")
    def poweroff():
        if not config.allow_poweroff:
            return (
                jsonify(
                    status="error",
                    message=(
                        "Poweroff is disabled. Set AMR_ALLOW_POWEROFF=1 to arm "
                        "shutdown of this computer."
                    ),
                ),
                403,
            )
        runner = config.poweroff_fn or default_poweroff
        try:
            runner()
        except Exception as exc:
            logger.warning("poweroff failed: %s", exc)
            return jsonify(status="error", message=str(exc)), 500
        return jsonify(status="success", message="shutdown command accepted")

    return app


def _wheel_param(name: str) -> int | None:
    raw = request.args.get(name, "")
    if raw == "":
        return None
    try:
        return int(raw, 10)
    except ValueError:
        return None


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="AMR Mission Control server")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--serial-port", default=None)
    parser.add_argument("--baud", type=int, default=None)
    parser.add_argument("--map-path", default=None)
    parser.add_argument("--mock-serial", action="store_true")
    parser.add_argument("--allow-poweroff", action="store_true")
    args = parser.parse_args()
    config = config_from_env()
    if args.host is not None:
        config.host = args.host
    if args.port is not None:
        config.port = args.port
    if args.serial_port is not None:
        config.serial_port = args.serial_port
    if args.baud is not None:
        config.baud = args.baud
    if args.map_path is not None:
        config.map_path = Path(args.map_path)
    if args.mock_serial:
        config.mock_serial = True
    if args.allow_poweroff:
        config.allow_poweroff = True
    app = create_app(config)
    logger.info(
        "serving Mission Control on %s:%s mock_serial=%s allow_poweroff=%s",
        config.host,
        config.port,
        config.mock_serial,
        config.allow_poweroff,
    )
    app.run(host=config.host, port=config.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
