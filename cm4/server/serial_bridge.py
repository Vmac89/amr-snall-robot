"""ESP32 link for the CM4 server.

Speaks the line protocol implemented in firmware/esp32. A mock stands in for
the DevKit when --mock-serial is set. Mock tick counts are not encoder
measurements.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

# Same limits as firmware/esp32/include/config.h.
WHEEL_MIN = -255
WHEEL_MAX = 255
HEARTBEAT_S = 0.2
FIRMWARE_COMMAND_TIMEOUT_S = 0.5
TELEMETRY_PERIOD_S = 0.1
# Arbitrary mock scale: PWM counts per telemetry period. Not a motor constant.
MOCK_TICKS_PER_PERIOD_DIVISOR = 32
# Fixed stand-in so tests can parse the battery field. Not a pack voltage.
MOCK_BATT_MV = 3300


@dataclass
class _Pending:
    line: str
    care: bool
    event: threading.Event
    response: str = ""
    sent_at: float = 0.0


class MockEsp32:
    """In-process stand-in for the ESP32 firmware protocol.

    Tick changes while a non-zero DRIVE is latched are a test aid. They do
    not correspond to hall-encoder counts on the JGA25-370 motors.
    """

    def __init__(self) -> None:
        self.left = 0
        self.right = 0
        self.ticks_l = 0
        self.ticks_r = 0
        self.motion = False
        self.telem = False
        self.last_heartbeat = time.monotonic()
        self._next_telem = time.monotonic() + TELEMETRY_PERIOD_S
        self._out: queue.Queue[str] = queue.Queue()

    def write_line(self, line: str) -> None:
        self._handle_command(line.strip())

    def read_line(self) -> str | None:
        try:
            return self._out.get_nowait()
        except queue.Empty:
            return None

    def poll(self) -> None:
        now = time.monotonic()
        if self.motion and now - self.last_heartbeat > FIRMWARE_COMMAND_TIMEOUT_S:
            self.motion = False
            self.left = 0
            self.right = 0
            self._emit("ERR command timeout")
        if self.telem and now >= self._next_telem:
            self._next_telem = now + TELEMETRY_PERIOD_S
            if self.motion:
                self.ticks_l += self.left // MOCK_TICKS_PER_PERIOD_DIVISOR
                self.ticks_r += self.right // MOCK_TICKS_PER_PERIOD_DIVISOR
            self._emit(f"ENC {self.ticks_l} {self.ticks_r} {MOCK_BATT_MV}")

    def close(self) -> None:
        return None

    def _emit(self, line: str) -> None:
        self._out.put(line)

    def _refresh(self) -> None:
        self.last_heartbeat = time.monotonic()

    def _handle_command(self, line: str) -> None:
        if line == "":
            return
        parts = line.split()
        cmd = parts[0]
        if cmd == "PING" and len(parts) == 1:
            self._refresh()
            self._emit("PONG")
            return
        if cmd == "STOP" and len(parts) == 1:
            self.left = 0
            self.right = 0
            self.motion = False
            self._refresh()
            self._emit("OK")
            return
        if cmd == "DRIVE" and len(parts) == 3:
            try:
                left = int(parts[1])
                right = int(parts[2])
            except ValueError:
                self._emit("ERR expected DRIVE <left> <right>")
                return
            if left < WHEEL_MIN or left > WHEEL_MAX or right < WHEEL_MIN or right > WHEEL_MAX:
                self._emit("ERR value out of range")
                return
            self.left = left
            self.right = right
            self.motion = left != 0 or right != 0
            self._refresh()
            self._emit("OK")
            return
        if cmd == "ENC" and len(parts) == 1:
            self._refresh()
            self._emit(f"ENC {self.ticks_l} {self.ticks_r} {MOCK_BATT_MV}")
            return
        if cmd == "TELEM" and len(parts) == 2 and parts[1] in ("0", "1"):
            self.telem = parts[1] == "1"
            self._refresh()
            self._emit("OK")
            return
        if cmd == "HELP" and len(parts) == 1:
            self._refresh()
            self._emit("OK HELP PING STOP DRIVE ENC TELEM")
            return
        self._emit("ERR unknown command")


class SerialPort:
    """pyserial wrapper. Constructing it opens the port."""

    def __init__(self, path: str, baud: int) -> None:
        import serial

        self._ser = serial.Serial(path, baud, timeout=0.05)

    def write_line(self, line: str) -> None:
        self._ser.write((line + "\n").encode("ascii"))

    def read_line(self) -> str | None:
        raw = self._ser.readline()
        if not raw:
            return None
        text = raw.decode("ascii", "replace").strip()
        return text or None

    def poll(self) -> None:
        return None

    def close(self) -> None:
        self._ser.close()


class SerialBridge:
    """Owns the ESP32 port. Repeats a non-zero DRIVE as a heartbeat."""

    def __init__(self, port_factory, mock: bool) -> None:
        self._factory = port_factory
        self.mock = mock
        self._port = None
        self._queue: queue.Queue[_Pending] = queue.Queue()
        self._waiting: _Pending | None = None
        self._lock = threading.Lock()
        self._desired = (0, 0)
        self._enc: tuple[int, int] | None = None
        self._batt_mv: int | None = None
        self.connected = False
        self.last_error = ""
        self._running = True
        self._next_heartbeat = 0.0
        self._thread = threading.Thread(target=self._run, name="esp32-serial", daemon=True)

    def start(self) -> None:
        self._try_open()
        if self._port is not None:
            self._queue.put(_Pending("TELEM 1", False, threading.Event()))
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._close_port()

    def drive(self, left: int, right: int) -> str:
        with self._lock:
            self._desired = (left, right)
        return self._submit(f"DRIVE {left} {right}")

    def estop(self) -> str:
        with self._lock:
            self._desired = (0, 0)
        return self._submit("STOP")

    def ping(self) -> str:
        return self._submit("PING")

    def snapshot(self) -> dict:
        with self._lock:
            enc = self._enc
            desired = self._desired
            connected = self.connected
            error = self.last_error
            batt_mv = self._batt_mv
        return {
            "enc_left": None if enc is None else enc[0],
            "enc_right": None if enc is None else enc[1],
            "batt_mv": batt_mv,
            "drive_left": desired[0],
            "drive_right": desired[1],
            "serial_connected": connected,
            "serial_mock": self.mock,
            "serial_error": error,
        }

    def _submit(self, line: str) -> str:
        with self._lock:
            connected = self.connected
            error = self.last_error
        if not connected:
            raise ConnectionError(error or "ESP32 serial link is down")
        pending = _Pending(line, True, threading.Event())
        self._queue.put(pending)
        if not pending.event.wait(1.5):
            raise TimeoutError(line)
        return pending.response

    def _try_open(self) -> None:
        if self._port is not None:
            return
        try:
            self._port = self._factory()
        except Exception as exc:
            with self._lock:
                self.connected = False
                self.last_error = str(exc)
            return
        with self._lock:
            self.connected = True
            self.last_error = ""

    def _close_port(self) -> None:
        port = self._port
        self._port = None
        with self._lock:
            self.connected = False
        if port is not None:
            close = getattr(port, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:
                    pass

    def _fail_waiting(self, message: str) -> None:
        waiting = self._waiting
        self._waiting = None
        if waiting is not None and waiting.care:
            waiting.response = message
            waiting.event.set()

    def _run(self) -> None:
        while self._running:
            if self._port is None:
                self._try_open()
                if self._port is None:
                    time.sleep(1.0)
                    continue
                self._queue.put(_Pending("TELEM 1", False, threading.Event()))
            try:
                self._port.poll()
                self._drain()
                if self._waiting is not None:
                    if time.monotonic() - self._waiting.sent_at > 1.0:
                        failed = self._waiting
                        self._waiting = None
                        if failed.care:
                            failed.response = "ERR serial timeout"
                            failed.event.set()
                    else:
                        time.sleep(0.02)
                    continue
                pending = self._pop()
                now = time.monotonic()
                if pending is None and self._moving() and now >= self._next_heartbeat:
                    with self._lock:
                        left, right = self._desired
                    pending = _Pending(
                        f"DRIVE {left} {right}", False, threading.Event()
                    )
                    self._next_heartbeat = now + HEARTBEAT_S
                if pending is None:
                    time.sleep(0.02)
                    continue
                self._port.write_line(pending.line)
                pending.sent_at = time.monotonic()
                self._waiting = pending
            except Exception as exc:
                with self._lock:
                    self.last_error = str(exc)
                self._fail_waiting("ERR serial " + str(exc))
                self._close_port()
                time.sleep(1.0)

    def _pop(self) -> _Pending | None:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def _moving(self) -> bool:
        with self._lock:
            left, right = self._desired
        return left != 0 or right != 0

    def _drain(self) -> None:
        assert self._port is not None
        for _ in range(20):
            line = self._port.read_line()
            if not line:
                return
            self._handle(line)

    def _handle(self, line: str) -> None:
        if line.startswith("ENC "):
            parts = line.split()
            if len(parts) >= 3:
                try:
                    left = int(parts[1])
                    right = int(parts[2])
                    batt_mv = int(parts[3]) if len(parts) >= 4 else None
                except ValueError:
                    return
                with self._lock:
                    self._enc = (left, right)
                    if batt_mv is not None:
                        self._batt_mv = batt_mv
            return
        if line == "READY":
            return
        if line.startswith("ERR"):
            with self._lock:
                self.last_error = line
        waiting = self._waiting
        if waiting is None:
            return
        self._waiting = None
        waiting.response = line
        waiting.event.set()
