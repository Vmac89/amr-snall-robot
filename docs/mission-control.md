# Mission control page

`web/mission-control/index.html` is the ROBZONE Mission Control 11.2 dashboard, stored as supplied. Opening it is described in the repository README.

## How the page talks to a host

The script uses same-origin HTTP `fetch` and an `<img>` URL. There is no WebSocket client in the file, and the page does not open a serial port.

Every path below is relative, so the browser sends it to the host that served the HTML. The on-page wording treats that host as the Raspberry Pi. This repository does not include a server for these routes.

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

## Relation to the ESP32 / CM4 serial protocol

The ESP32 scaffold speaks the line protocol in [serial-protocol.md](serial-protocol.md) on USB serial and on UART2 toward the CM4: `DRIVE`, `STOP`, `ENC`, and the other commands listed there.

The dashboard does not send those lines. Nothing in this repository receives `/api/*`, `/tilt/*`, or `/video_feed`, and nothing forwards them to the ESP32 UART.

Concrete differences already visible in the two files:

- The emergency-stop control posts `/api/cmd?action=ESTOP`. The firmware command that coasts the motors is the serial line `STOP`. The HTML never writes `STOP`.
- `/api/data` reads `temp`, `batt`, and `dist`. The ESP32 firmware does not emit those fields. Its telemetry line is `ENC <left_ticks> <right_ticks>`.
- Keyboard motion and mission playback move a cursor on the canvas. They are not `DRIVE` commands.
- A stored station IP is map data inside the page. The serial link in this repo is UART2 (GPIO 16/17), not a connection opened from this HTML file.
