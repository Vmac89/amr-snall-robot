# Mission control page

`web/mission-control/index.html` is the ROBZONE Mission Control 11.2 dashboard. The layout is the original page, plus a drive pad and a RESET ESTOP button that use the existing button style. Arrow keys, that pad, and mission playback now post drive commands. Opening it is described in the repository README.

## How the page talks to a host

The script uses same-origin HTTP `fetch` and an `<img>` URL. There is no WebSocket client in the file, and the page does not open a serial port.

Every path below is relative, so the browser sends it to the host that served the HTML. The on-page wording treats that host as the Raspberry Pi. `cm4/server` is that host process. Setup is in [cm4/server/README.md](../cm4/server/README.md).

| Call | What the page does with it |
| --- | --- |
| `GET /video_feed` | `src` of the live-feed image. If the image fails, the overlay text is `KINECT_OFFLINE // BANDWIDTH_SAVED`. The toggle sets that `src` back to `/video_feed` or clears it. |
| `GET /api/data` | Polled every 1 s. JSON fields read by the page: `temp` (shown as °C), `batt` (shown as V), `dist` (shown as CM). A missing value is shown as `n/a`. Numeric 0 is shown as 0. `estop_latched` marks the stop button. |
| `GET /tilt/up`, `GET /tilt/down` | Tilt buttons. The page logs JSON field `angle`. |
| `POST /api/cmd?action=ESTOP` | Emergency-stop button. Latches on the server until RESET. |
| `POST /api/cmd?action=RESET` | RESET ESTOP button. Clears the latch. No serial line. |
| `POST /api/cmd?action=DRIVE&left=<n>&right=<n>` | Arrow keys, the on-screen pad, and mission playback. Repeated about every 150 ms while a control is held. `0 0` on release, blur, and page hide. |
| `POST /api/save_map` | Save-map button. JSON body with `stations`, `trail`, `robotPos`, and `startPoint`. The page treats `status` equal to `success` as a completed save. |
| `GET /api/read_map` | Read-saved-map button. Expects JSON with those same fields. The alert text names `ROBZONE_MAP.JSON`. |
| `POST /api/poweroff` | Shutdown button, after a confirm dialog. JSON fields read: `status`, `message`. |

`SAVE_MAP` uses `/api/save_map` rather than `/api/cmd`.

## What the page keeps in the browser

Outside teaching and mission playback, the canvas arrow follows `odom` from `GET /api/data` (server pose from encoder ticks, including mock ticks). Polls are about 5 times a second, and the marker eases between samples. `PX_PER_M` in the page is a view scale, not a measured map. RESET CURSOR recenters that view. Teaching still draws the canvas path from the arrow keys. The same keys also post `DRIVE` unless a mission is playing. Held PWM is `DRIVE_PWM` (80), a bench duty in the page script, not a measured speed. Forward is both wheels positive, back is both negative, left is left-negative/right-positive, right is the opposite.

Mission playback still walks the canvas trace. It also posts `DRIVE`. Screen-up (heading `-π/2`) is treated as robot forward. If the heading is more than 0.5 rad off that, the page spins in place. Both of those choices need a check on the floor. A station pause posts `DRIVE 0 0` for the pause.

A station type of `PHYSICAL (ESP32 Node)` stores an IP address. The form's default value is `10.42.0.50`. The station list displays it, and a map save includes it in the JSON. The script never sends a request to that address.

## What the CM4 server does with those routes

`cm4/server/server.py` serves the HTML and implements every route in the table above. The page does not open a serial port. The server does.

The ESP32 line protocol is documented in [serial-protocol.md](serial-protocol.md). Placeholders are in `cm4/server/calibration.py`. The bench checklist is [bring-up.md](bring-up.md).

| HTTP | Effect |
| --- | --- |
| `POST /api/cmd?action=ESTOP` | Serial `STOP`, and a server latch. Later `DRIVE` returns HTTP 409 until `RESET`. |
| `POST /api/cmd?action=RESET` | Clears the latch and the watchdog-tripped flag. No serial line. |
| `POST /api/cmd?action=STOP` | Serial `STOP` without latching. |
| `POST /api/cmd?action=DRIVE&left=<n>&right=<n>` | Serial `DRIVE <n> <n>`, or `STOP` when the command is `0 0` or an obstacle clamp zeroes it. Each `n` must be an integer from `-255` to `255`. |
| `POST /api/cmd?action=PING` | Serial `PING`. Not used by the page. Does not refresh the drive watchdog. |
| `GET /api/data` fields `enc_left`, `enc_right` | Latest `ENC` line. After connect the server sends `TELEM 1`. |
| `GET /api/data` field `batt` | `battery_mv / 1000`, two decimals, or `n/a` before the first sample. `batt_calibrated` follows `AMR_BATT_CALIBRATED` and defaults false. |
| `GET /api/data` field `dist` | Centimetres from the Kinect depth center window when a frame exists, otherwise `n/a`. `dist_calibrated` is always false. |
| `GET /api/data` field `odom` | Pose from encoder deltas. `calibrated` stays false until `AMR_GEOMETRY_CALIBRATED=1`. |
| `GET /api/data` field `temp` | CM4 CPU thermal zone, in °C, when `/sys/class/thermal/thermal_zone0/temp` exists. `n/a` when it does not. Not an ESP32 reading. |
| `GET /video_feed` | MJPEG. A libfreenect frame when that library returns one, otherwise a placeholder JPEG. |
| `GET /tilt/up`, `GET /tilt/down` | Moves a tilt setpoint by 5 degrees, clamped to ±30 (libfreenect `TILT_MAX_DEGREES`). The call is forwarded only when libfreenect accepts it. `applied` is false when it does not. The page still logs "Tilt success" because it only prints `angle`. |
| `POST /api/save_map`, `GET /api/read_map` | A JSON file on the CM4. No serial traffic. `read_map` is HTTP 404 until a map has been saved, which is the page's empty-file path. |
| `POST /api/poweroff` | `shutdown -h now` only when `AMR_ALLOW_POWEROFF=1` or `--allow-poweroff` is set. Default is off, and the route then returns HTTP 403 with `status: error`. |

The page must repeat `DRIVE` while it wants motion. If those posts stop for `AMR_CLIENT_WATCHDOG_S` (0.5 s), the server sends `STOP`. Polling `/api/data` does not refresh that timer. While the client still wants motion, the server repeats `DRIVE` to the ESP32 every 200 ms so the firmware's 500 ms timeout does not coast the motors. `ESTOP` is a latch. The watchdog is only a coast.

If `dist` is a number below `AMR_OBSTACLE_CM` (placeholder 40), positive wheel commands are dropped and reverse is still allowed. No distance means no clamp.

`--mock-serial` answers the same lines without opening a UART. Its tick counts move while a non-zero `DRIVE` is latched (`command // 32` per 100 ms). Its battery field is a fixed 3300 mV so the parser can be tested. Neither number is a measurement.

A physical station's stored IP is still only map JSON. The server does not open a TCP connection to it. The serial link remains the UART in the firmware pin map. Do not run the ROS 2 base driver at the same time.
