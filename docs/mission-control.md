# Mission control page

`web/mission-control/index.html` is the ROBZONE Mission Control 11.2 dashboard, stored as supplied. Opening it is described in the repository README.

## How the page talks to a host

The script uses same-origin HTTP `fetch` and an `<img>` URL. There is no WebSocket client in the file, and the page does not open a serial port.

Every path below is relative, so the browser sends it to the host that served the HTML. The on-page wording treats that host as the Raspberry Pi. `cm4/server` is that host process. Setup is in [cm4/server/README.md](../cm4/server/README.md).

| Call | What the page does with it |
| --- | --- |
| `GET /video_feed` | `src` of the live-feed image. If the image fails, the overlay text is `KINECT_OFFLINE // BANDWIDTH_SAVED`. The toggle sets that `src` back to `/video_feed` or clears it. |
| `GET /api/data` | Polled every 1 s. JSON fields read by the page: `temp` (shown as °C), `batt` (shown as V), `dist` (shown as CM). |
| `GET /tilt/up`, `GET /tilt/down` | Tilt buttons. The page logs JSON field `angle`. |
| `POST /api/cmd?action=ESTOP` | Emergency-stop button. Empty body. The response is ignored. |
| `POST /api/save_map` | Save-map button. JSON body with `stations`, `trail`, `robotPos`, and `startPoint`. The page treats `status` equal to `success` as a completed save. |
| `GET /api/read_map` | Read-saved-map button. Expects JSON with those same fields. The alert text names `ROBZONE_MAP.JSON`. |
| `POST /api/poweroff` | Shutdown button, after a confirm dialog. JSON fields read: `status`, `message`. |

`sendCmd` is only invoked for `ESTOP` and `SAVE_MAP`. `SAVE_MAP` uses `/api/save_map` rather than `/api/cmd`.

## What the page keeps in the browser

Arrow keys during teaching, the path trace, mission repeat, and the pause at a station update the canvas only. Those paths do not call `fetch`.

A station type of `PHYSICAL (ESP32 Node)` stores an IP address. The form's default value is `10.42.0.50`. The station list displays it, and a map save would include it in the JSON. The script never sends a request to that address.

## What the CM4 server does with those routes

`cm4/server/server.py` serves the HTML and implements every route in the table above. The page is unchanged: it still does not open a serial port, and its arrow keys still do not leave the browser.

The ESP32 line protocol is documented in [serial-protocol.md](serial-protocol.md). The server is the piece that writes it on the CM4 UART (or on the mock link).

| HTTP | Effect |
| --- | --- |
| `POST /api/cmd?action=ESTOP` or `action=STOP` | Serial `STOP`. Clears the latched wheel command. |
| `POST /api/cmd?action=DRIVE&left=<n>&right=<n>` | Serial `DRIVE <n> <n>`. Each `n` must be an integer from `-255` to `255`. |
| `POST /api/cmd?action=PING` | Serial `PING`. Not used by the page. |
| `GET /api/data` fields `enc_left`, `enc_right` | Latest `ENC` line. After connect the server sends `TELEM 1`, so the firmware emits `ENC` on its telemetry timer. |
| `GET /api/data` fields `batt`, `dist` | The string `n/a`. This protocol has no battery voltage and no range sample. A truthy token keeps the page from substituting `12.4` and `0`. |
| `GET /api/data` field `temp` | CM4 CPU thermal zone, in °C, when `/sys/class/thermal/thermal_zone0/temp` exists. `n/a` when it does not. Not an ESP32 reading. |
| `GET /video_feed` | MJPEG. A libfreenect frame when that library returns one, otherwise a placeholder JPEG. |
| `GET /tilt/up`, `GET /tilt/down` | Moves a tilt setpoint by 5 degrees, clamped to ±30 (libfreenect `TILT_MAX_DEGREES`). The call is forwarded only when libfreenect accepts it. `applied` is false when it does not. The page still logs "Tilt success" because it only prints `angle`. |
| `POST /api/save_map`, `GET /api/read_map` | A JSON file on the CM4. No serial traffic. `read_map` is HTTP 404 until a map has been saved, which is the page's empty-file path. |
| `POST /api/poweroff` | `shutdown -h now` only when `AMR_ALLOW_POWEROFF=1` or `--allow-poweroff` is set. Default is off, and the route then returns HTTP 403 with `status: error`. |

While either wheel command is non-zero, the server repeats the `DRIVE` line every 200 ms. That is inside the firmware's 500 ms command timeout, so a live link does not coast the motors between repeats. `ESTOP` stops the repeat.

`--mock-serial` answers the same lines without opening a UART. Its tick counts move while a non-zero `DRIVE` is latched (`command // 32` per 100 ms). Those counts are not hall-encoder measurements.

A physical station's stored IP is still only map JSON. The server does not open a TCP connection to it. The serial link remains the UART in the firmware pin map.
