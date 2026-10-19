"""Mission Control HTTP server for the Raspberry Pi CM4.

Serves web/mission-control/index.html and the routes that page calls.
Wheel commands go out as ESP32 serial DRIVE / STOP lines. Encoder samples
and the firmware battery field come back on /api/data. Pose uses the
placeholders in calibration.py.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from calibration import (
    CLIENT_WATCHDOG_S,
    LEFT_TICK_SIGN,
    OBSTACLE_STOP_CM,
    RIGHT_TICK_SIGN,
    TICKS_PER_REV,
    TRACK_WIDTH_M,
    WHEEL_DIAMETER_M,
)
from kinect_motor import KinectMotor
from odometry import Odometry
from safety import EstopLatched, Safety
from serial_bridge import WHEEL_MAX, WHEEL_MIN, MockEsp32, SerialBridge, SerialPort
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
    watchdog_s: float = CLIENT_WATCHDOG_S
    obstacle_cm: float = OBSTACLE_STOP_CM
    wheel_diameter_m: float = WHEEL_DIAMETER_M
    track_width_m: float = TRACK_WIDTH_M
    ticks_per_rev: float = TICKS_PER_REV
    left_tick_sign: int = LEFT_TICK_SIGN
    right_tick_sign: int = RIGHT_TICK_SIGN
    # Set true only after the placeholders above have been replaced with
    # measurements. The server does not infer this from the numbers.
    geometry_calibrated: bool = False
    obstacle_calibrated: bool = False
    batt_calibrated: bool = False


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if raw == "":
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if raw == "":
        return default
    return int(raw)


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
        watchdog_s=_env_float("AMR_CLIENT_WATCHDOG_S", CLIENT_WATCHDOG_S),
        obstacle_cm=_env_float("AMR_OBSTACLE_CM", OBSTACLE_STOP_CM),
        wheel_diameter_m=_env_float("AMR_WHEEL_DIAMETER_M", WHEEL_DIAMETER_M),
        track_width_m=_env_float("AMR_TRACK_WIDTH_M", TRACK_WIDTH_M),
        ticks_per_rev=_env_float("AMR_TICKS_PER_REV", TICKS_PER_REV),
        left_tick_sign=_env_int("AMR_LEFT_TICK_SIGN", LEFT_TICK_SIGN),
        right_tick_sign=_env_int("AMR_RIGHT_TICK_SIGN", RIGHT_TICK_SIGN),
        geometry_calibrated=_env_flag("AMR_GEOMETRY_CALIBRATED"),
        obstacle_calibrated=_env_flag("AMR_OBSTACLE_CALIBRATED"),
        batt_calibrated=_env_flag("AMR_BATT_CALIBRATED"),
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


def _format_batt(batt_mv: int | None) -> str:
    if batt_mv is None:
        return "n/a"
    return f"{batt_mv / 1000.0:.2f}"


def _watchdog_loop(stop: threading.Event, safety: Safety, bridge: SerialBridge) -> None:
    while not stop.wait(0.05):
        if not safety.expired():
            continue
        safety.note_watchdog()
        try:
            bridge.estop()
        except (ConnectionError, TimeoutError) as exc:
            logger.warning("watchdog stop failed: %s", exc)
        logger.info("client drive watchdog expired; motors coasted")


def _odom_loop(stop: threading.Event, odom: Odometry, bridge: SerialBridge) -> None:
    while not stop.wait(0.05):
        snap = bridge.snapshot()
        if snap["enc_left"] is None or snap["enc_right"] is None:
            continue
        odom.update(snap["enc_left"], snap["enc_right"])


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
    motor = KinectMotor()
    safety = Safety(
        watchdog_s=config.watchdog_s,
        obstacle_cm=config.obstacle_cm,
        obstacle_calibrated=config.obstacle_calibrated,
    )
    odom = Odometry(
        wheel_diameter_m=config.wheel_diameter_m,
        track_width_m=config.track_width_m,
        ticks_per_rev=config.ticks_per_rev,
        left_sign=config.left_tick_sign,
        right_sign=config.right_tick_sign,
        calibrated=config.geometry_calibrated,
    )
    stop = threading.Event()
    watchdog = threading.Thread(
        target=_watchdog_loop, args=(stop, safety, bridge), name="client-watchdog", daemon=True
    )
    odom_thread = threading.Thread(
        target=_odom_loop, args=(stop, odom, bridge), name="odometry", daemon=True
    )
    bridge.start()
    kinect.start()
    watchdog.start()
    odom_thread.start()
    app.extensions["amr_bridge"] = bridge
    app.extensions["amr_kinect"] = kinect
    app.extensions["amr_motor"] = motor
    app.extensions["amr_config"] = config
    app.extensions["amr_safety"] = safety
    app.extensions["amr_odom"] = odom
    app.extensions["amr_stop"] = stop
    app.extensions["amr_threads"] = (watchdog, odom_thread)

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
        temp = cpu_temp_c()
        body["temp"] = temp if temp is not None else "n/a"
        # Firmware millivolts already include kBatteryDividerRatio. The
        # calibrated flag stays false until AMR_BATT_CALIBRATED=1.
        body["batt"] = _format_batt(body.pop("batt_mv"))
        body["batt_calibrated"] = config.batt_calibrated
        if kinect.distance_cm is None:
            body["dist"] = "n/a"
        else:
            body["dist"] = kinect.distance_cm
        body["dist_note"] = kinect.distance_note
        body["dist_calibrated"] = False
        body["kinect_live"] = kinect.live
        body["tilt_setpoint_deg"] = motor.angle
        body["estop_latched"] = safety.latched
        body["safety"] = safety.snapshot()
        body["odom"] = odom.snapshot()
        return jsonify(body)

    @app.get("/tilt/<direction>")
    def tilt(direction: str):
        if direction not in ("up", "down"):
            return jsonify(status="error", message="unknown tilt direction"), 404
        return jsonify(motor.nudge(direction))

    @app.post("/api/led")
    def api_led():
        raw = request.args.get("value", "")
        try:
            code = int(raw, 10)
        except ValueError:
            return (
                jsonify(
                    status="error",
                    message="LED value must be an integer 0..255",
                    applied=False,
                ),
                400,
            )
        if code < 0 or code > 255:
            return (
                jsonify(
                    status="error",
                    message="LED value must be an integer 0..255",
                    applied=False,
                ),
                400,
            )
        return jsonify(motor.set_led(code))

    @app.post("/api/cmd")
    def api_cmd():
        action = request.args.get("action", "").strip()
        obstacle_stop = False
        try:
            if action == "ESTOP":
                safety.estop()
                serial_line = bridge.estop()
                mapped = "STOP"
            elif action == "RESET":
                safety.reset()
                return jsonify(status="ok", action=action, mapped="RESET", serial="")
            elif action == "STOP":
                safety.note_coast()
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
                try:
                    left, right = safety.accept_drive(left, right, kinect.distance_cm)
                except EstopLatched as exc:
                    return jsonify(status="error", message=str(exc), estop_latched=True), 409
                obstacle_stop = safety.obstacle_stop
                if left == 0 and right == 0:
                    serial_line = bridge.estop()
                    mapped = "STOP"
                else:
                    serial_line = bridge.drive(left, right)
                    mapped = f"DRIVE {left} {right}"
            else:
                return (
                    jsonify(
                        status="error",
                        message="unsupported action; use ESTOP, STOP, RESET, DRIVE, or PING",
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
            jsonify(
                status=status,
                action=action,
                mapped=mapped,
                serial=serial_line,
                obstacle_stop=obstacle_stop,
                estop_latched=safety.latched,
            ),
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
