# CM4 Mission Control server

Flask process that serves `web/mission-control/index.html` and the HTTP routes that page calls. It runs on the Raspberry Pi CM4. Wheel commands and encoder samples use the ESP32 line protocol in [docs/serial-protocol.md](../../docs/serial-protocol.md).

The page posts `DRIVE` from the arrow keys, the on-screen pad, and mission playback, and repeats that post about every 150 ms while a control is held. The same routes from curl:

```bash
curl -X POST 'http://127.0.0.1:8080/api/cmd?action=DRIVE&left=80&right=-40'
curl -X POST 'http://127.0.0.1:8080/api/cmd?action=ESTOP'
curl -X POST 'http://127.0.0.1:8080/api/cmd?action=RESET'
```

`ESTOP` is written as serial `STOP` and latches until `RESET` (HTTP 409 on later `DRIVE`). `STOP` coasts without latching. `DRIVE` is written as `DRIVE <left> <right>` with each value limited to `-255..255`. If the browser stops repeating `DRIVE` for `AMR_CLIENT_WATCHDOG_S` (0.5 s), the server sends `STOP`. `/api/data` and `PING` do not refresh that timer. While the client still wants motion, the server repeats `DRIVE` to the ESP32 every 200 ms so the firmware's 500 ms timeout does not coast the motors.

`GET /api/data` includes `enc_left` and `enc_right` from `ENC` lines, and `batt` from the firmware `battery_mv` field (millivolts / 1000). `batt_calibrated` stays false until `AMR_BATT_CALIBRATED=1`. `dist` is centimetres from the Kinect depth center window when a frame exists, otherwise `n/a`. `dist_calibrated` is always false. `odom` is the pose integrated from tick deltas using the placeholders in `calibration.py`; `odom.calibrated` stays false until `AMR_GEOMETRY_CALIBRATED=1`. `temp` is the CM4 CPU thermal zone when `/sys/class/thermal/thermal_zone0/temp` exists, and `n/a` when that file is missing. It is not a motor or pack temperature.

If `dist` is a number below `AMR_OBSTACLE_CM` (placeholder 40), positive wheel commands are zeroed and reverse is still allowed. A missing distance does not block motion.

`/video_feed` is an MJPEG stream. If `libfreenect` can import and return a frame, that frame is JPEG-encoded. If the camera raises, including `Failed to fetch const shift`, that failure is latched and the stream stays on the placeholder JPEG. libfreenect is not used for tilt: on this CM4, `freenect.open_device` followed by a tilt call segfaults. Tilt buttons call `GET /tilt/up` and `GET /tilt/down`, which send a pyusb control transfer to the Kinect motor `045e:02b0`. Each step changes a setpoint by 5 degrees, clamped to ±30. `POST /api/led?value=1` sets the LED green (the code tested on this unit); other integer codes 0..255 are passed through, and a non-integer is HTTP 400. A missing motor still returns HTTP 200 with `applied` false. The page logs "Tilt success" whenever the tilt JSON parses; `applied` is the field that says whether USB succeeded. The Kinect is model `1414` (Xbox 360, Kinect v1). apt `libfreenect` 0.5.3 on Raspberry Pi OS Bookworm did not open it. The source build and the udev note are in [docs/bring-up.md](../../docs/bring-up.md).

Map save/load uses a JSON file, `cm4/server/data/robzone_map.json` unless `AMR_MAP_PATH` is set. The page's alert text says `ROBZONE_MAP.JSON`; that string is in the HTML and is not the filename. `GET /api/read_map` is 404 until the first successful save, which is the page's "nothing saved yet" path.

`POST /api/poweroff` does not shut the machine down unless `AMR_ALLOW_POWEROFF=1` (or `--allow-poweroff`) is set. The default is off, and the route then returns HTTP 403 with `status: error`. When it is armed, the server runs `shutdown -h now`. The process needs permission for that command. This halts the computer the server is running on.

Mock serial (`--mock-serial` or `AMR_MOCK_SERIAL=1`) does not open a UART. It answers the same command lines as the firmware. While a non-zero `DRIVE` is latched, mock tick counts change by `command // 32` once per 100 ms telemetry period. The mock battery field is a fixed 3300 mV. Neither number is an encoder count, gear ratio, pack voltage, or measured speed.

Wheel diameter, track width, and ticks per revolution are placeholders. The server still integrates a pose so `/api/data` has an `odom` object, and it labels that pose uncalibrated. `cmd_vel` mixing lives in the ROS 2 node, which must not run while this server holds the UART. The bench steps are [docs/bring-up.md](../../docs/bring-up.md). `bash cm4/install.sh` from a login user on the CM4 installs the apt packages, adds `dialout`, and installs the systemd unit.

## Run without hardware

`bash cm4/install.sh` (from a login user, not root) installs `python3-flask`, `python3-serial`, `python3-pil`, and `python3-usb` into the system interpreter and points systemd at `/usr/bin/python3`. It does not create `cm4/server/.venv`. On a machine where that script has been run, from this directory:

```bash
python3 server.py --mock-serial --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080/`.

On a computer without those apt packages, use a venv instead. `install.sh` is not that path:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python3 server.py --mock-serial --host 127.0.0.1 --port 8080
```

Do not use apt `python3-freenect` / `libfreenect` 0.5.3 for this Kinect. On Raspberry Pi OS Bookworm that package fails with `Failed to fetch zero plane info`. Build libfreenect from source as written in [docs/bring-up.md](../../docs/bring-up.md). If the import or the device open fails, the placeholder frame is what `/video_feed` serves.

```bash
python3 -m unittest test_server.py
```

## Run against the ESP32

The UART device node on this CM4 carrier is still unset. `/dev/ttyAMA0` is the default placeholder. Pick the node that matches the carrier and the device tree, then:

```bash
python3 server.py --serial-port /dev/ttyAMA0 --baud 115200 --host 0.0.0.0 --port 8080
```

The account needs access to that device (on Raspberry Pi OS, typically membership in `dialout`). If the port cannot be opened, HTTP still serves the page and `/api/data` reports `serial_connected: false`. Mock mode is not implied by a missing port; encoder fields stay null instead of being invented.

| Variable | Default | Meaning |
| --- | --- | --- |
| `AMR_HOST` | `0.0.0.0` | Bind address |
| `AMR_PORT` | `8080` | Bind port |
| `AMR_SERIAL_PORT` | `/dev/ttyAMA0` | Placeholder UART path |
| `AMR_SERIAL_BAUD` | `115200` | 8N1, same as the firmware |
| `AMR_MOCK_SERIAL` | off | `1` enables the in-process ESP32 stand-in |
| `AMR_ALLOW_POWEROFF` | off | `1` arms `shutdown -h now` |
| `AMR_MAP_PATH` | `cm4/server/data/robzone_map.json` | Map file |
| `AMR_CLIENT_WATCHDOG_S` | `0.5` | Coast if `DRIVE` posts stop |
| `AMR_OBSTACLE_CM` | `40` | CALIBRATE. Forward stop distance |
| `AMR_WHEEL_DIAMETER_M` | `0.065` | CALIBRATE |
| `AMR_TRACK_WIDTH_M` | `0.20` | CALIBRATE |
| `AMR_TICKS_PER_REV` | `422.4` | CALIBRATE. `11 * 9.6 * 4` until a 10-turn count replaces the gear ratio |
| `AMR_LEFT_TICK_SIGN` | `1` | CALIBRATE. `-1` flips that wheel |
| `AMR_RIGHT_TICK_SIGN` | `1` | CALIBRATE |
| `AMR_GEOMETRY_CALIBRATED` | off | Set `1` only after a taped check |
| `AMR_OBSTACLE_CALIBRATED` | off | Reported only. Does not change the threshold |
| `AMR_BATT_CALIBRATED` | off | Set `1` only after the divider matches a meter |

## systemd

`amr-mission-control.service` is an example. Paths, `User=amr`, and `AMR_SERIAL_PORT` are placeholders to edit. `AMR_ALLOW_POWEROFF=0` in that file. `ExecStart` uses `/usr/bin/python3`, so that interpreter needs Flask, pyserial, and Pillow installed (the apt packages above, or point `ExecStart` at a venv). Copy the unit to `/etc/systemd/system/`, then `systemctl daemon-reload` and `systemctl enable --now amr-mission-control.service`. The service user must be able to write the map directory.
