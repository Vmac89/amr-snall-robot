# amr-snall-robot

Small home AMR (autonomous mobile robot) hobby project. This repository is the initial scaffold: firmware that can be flashed to the ESP32, a ROS 2 package skeleton for the Raspberry Pi CM4, and places to put printed parts and wiring notes.

Electrical and mechanical numbers for this robot are unset until they are measured. The tables below name the parts and leave ratings blank on purpose.

## Overview

Low-level control runs on an ESP32 DevKit V1: L298N PWM and direction for a differential drive, quadrature counts from the motor hall encoders, and a small serial protocol. High-level compute is a Raspberry Pi Compute Module 4 on a Waveshare CM4-Duino, with ROS 2 as the intended software stack. Depth sensing is a Microsoft Kinect for Xbox 360, model `1414`. That is a Kinect v1, so the matching library is libfreenect. The image used on this board is Raspberry Pi OS Lite (Bookworm).

The chassis and other mechanical parts are 3D printed. CAD and mesh files are not in the tree yet.

A static operator page, ROBZONE Mission Control 11.2, lives in `web/mission-control`. `cm4/server` is the Flask process that serves it and bridges wheel commands to the ESP32 serial protocol.

## Repository layout

| Path | Contents |
| --- | --- |
| `firmware/esp32` | PlatformIO project for the ESP32 DevKit V1. |
| `ros2_ws/src/amr_base` | ROS 2 bridge: `cmd_vel` to `DRIVE`, encoder `odom` and tf, optional libfreenect. Not built in this environment. |
| `hardware/3d-parts` | Future STL and STEP files. |
| `hardware/electronics` | Proposed pinout. |
| `web/mission-control` | ROBZONE Mission Control 11.2 dashboard (static HTML). |
| `cm4/server` | Flask server for that page, plus the ESP32 serial bridge. |
| `docs` | Serial protocol, dashboard HTTP notes, and the bring-up checklist. |
| `cm4/install.sh` | CM4 apt packages, `dialout`, and the systemd unit. Does not arm poweroff. |

## Hardware

| Qty | Part | Role | Recorded here |
| --- | --- | --- | --- |
| — | 3D-printed chassis and parts | Mechanical structure | No files yet. See `hardware/3d-parts`. |
| 1 | ESP32 DevKit V1 | Motor PWM, encoder counts, serial link | WROOM-32 DevKit assumed for the pin map. |
| 1 | Raspberry Pi CM4 on a Waveshare CM4-Duino | High-level compute, intended ROS 2 host | Raspberry Pi OS Lite (Bookworm). RAM and storage are unset. |
| 2 | JGA25-370 DC gear motor with hall encoder | Left and right differential drive | Rated voltage, gear ratio, and encoder counts are unset. This name covers more than one motor variant. |
| 1 | Microsoft Kinect for Xbox 360, model 1414 | Depth sensor | Kinect v1. USB data to the CM4. Power is its own 12 V adapter. |
| 1 | L298N motor driver | Dual H-bridge for the two motors | Module current rating and input thresholds are unset. |
| 1 | Step-down buck converter | Logic supply from the battery | Output voltage and current rating are unset. |
| 1 | 12 V battery | Main pack | Chemistry and capacity are unset. |

## Architecture

Motor current is drawn from the battery into the L298N motor supply. The buck feeds logic on the CM4 carrier and the ESP32. The ESP32-to-L298N link is PWM and direction, not motor current.

```mermaid
flowchart TD
  bat["12V battery"] --> buck["Step-down buck converter"]
  bat -->|"motor supply"| l298["L298N motor driver"]
  buck -->|"logic supply"| cm4["Raspberry Pi CM4 on Waveshare CM4-Duino"]
  buck -->|"logic supply"| esp["ESP32 DevKit V1"]
  esp -->|"PWM and direction"| l298
  l298 --> motors["JGA25-370 DC gear motors"]
  enc["Hall encoders"] --> esp
  kinect["Kinect 1414, Xbox 360, USB data"] --> cm4
  esp <-->|"serial"| cm4
```

## Wiring notes

Confirm these on the bench. Details and the proposed GPIO map are in [hardware/electronics/pinout.md](hardware/electronics/pinout.md).

- Tie battery negative, buck ground, L298N ground, ESP32 ground, and CM4 ground together.
- Measure the buck output before it is connected to the CM4 carrier or the ESP32. The carrier's required input voltage is unset. An ESP32 DevKit V1 is powered from USB or from its 5V/VIN pin; the 3V3 pin is an output of the DevKit's regulator.
- Confirm the JGA25-370 nameplate voltage before the 12 V pack lands on the L298N motor supply. The motor family includes more than one rated voltage.
- Remove the L298N `ENA` and `ENB` jumpers when those pins are driven by ESP32 PWM.
- ESP32 GPIO high is 3.3 V. Confirm that level is a valid high for the L298N inputs on this module, or level-shift the six control lines.
- Confirm the hall-encoder high level before it touches a GPIO. GPIO 34, 35, 36, and 39 have no internal pull-ups. A 5 V encoder swing can damage the ESP32.
- Fuse the motor supply. Stall current of these motors, and the continuous rating of this L298N module, are unset.
- Cross ESP32 UART2 TX/RX to the CM4 UART, and share ground. The carrier header and the Linux device node are unset. Both ends are expected to be 3.3 V logic; confirm the header.
- Leave ESP32 strapping pins (GPIO 0, 2, 12, 15), the USB console (GPIO 1 and 3), and the flash pins (GPIO 6–11) out of the harness.
- Kinect model `1414` data is USB into the CM4. Power it from its own 12 V adapter. Do not expect the sensor to run from the CM4 USB port alone.
- Many L298N boards can put an onboard regulator onto a `+5V` pin via a jumper. Confirm that jumper on the silkscreen before using the pin to power anything.

## Serial link

USB serial and UART2 both speak the line protocol in [docs/serial-protocol.md](docs/serial-protocol.md) at 115200 8N1. The CM4 sends per-wheel `DRIVE` commands. `ENC` includes a battery millivolts field from a proposed divider on GPIO 4; the firmware ratio is `1.0` until you enter the real divider. If the ESP32 is commanding motion and no valid command arrives for 500 ms, it coasts the motors. The CM4 server has a separate watchdog: it coasts if the browser stops repeating `DRIVE`.

## Firmware

PlatformIO project: `firmware/esp32`, environment `esp32dev`.

```bash
pio run -d firmware/esp32
```

The `espressif32` platform pinned in `platformio.ini` packages Arduino-ESP32 2.0.17, so PWM uses `ledcSetup` / `ledcAttachPin`. Upload (`pio run -t upload`) needs the DevKit on USB.

## ROS 2 workspace

`ros2_ws/src/amr_base` is the CM4 ROS 2 bridge. It was not compiled here (no ROS distro in this environment).

- `base_driver_node` opens the ESP32 UART, mixes `cmd_vel` into `DRIVE` with the placeholders in `cm4/server/calibration.py`, and publishes `odom` and tf from encoder ticks. Stop `cm4/server` first. Both cannot own the UART.
- `kinect_freenect_node` publishes image and depth topics when libfreenect is found at build time. Otherwise it stays quiet. Model `1414` is the Xbox 360 Kinect, which libfreenect targets. The Bookworm apt package did not open it; the source build is in [docs/bring-up.md](docs/bring-up.md). Camera intrinsics are zeros.

The ROS 2 distribution on the CM4 is not chosen. When one is installed:

```bash
cd ros2_ws
source /opt/ros/<distro>/setup.bash
colcon build --packages-select amr_base
```

## Roadmap

The software path for teleop, battery sense, Kinect distance, odometry, and a ROS 2 bridge is in the tree. What is left is measurement and hardware confirmation. The ordered checklist is [docs/bring-up.md](docs/bring-up.md).

1. Bench-check grounds, the buck voltage, the battery divider (meter it before GPIO 4), and the proposed pin map with the motors unplugged.
2. Flash the ESP32. Confirm `ENC` ticks and that `battery_mv` matches a meter after `kBatteryDividerRatio` is set. Wheels up, check motor direction.
3. Measure ticks per revolution, wheel diameter, and track width. Set the matching `AMR_*` values, then `AMR_GEOMETRY_CALIBRATED=1` only after a taped distance agrees with `odom`.
4. Finish the Kinect bring-up in [docs/bring-up.md](docs/bring-up.md). Model `1414` uses its 12 V adapter. `dist` stays uncalibrated until a tape check. `otg_mode=1` under `[cm4]` is still being verified. Then set `AMR_OBSTACLE_CM`.
5. Choose a ROS 2 distribution and `colcon build` `amr_base`. Do not run it together with `cm4/server`.
6. Add STL and STEP files under `hardware/3d-parts`, and record dimensions from those files or from the printed parts.

## Mission control

`web/mission-control/index.html` is the ROBZONE Mission Control 11.2 page. Arrow keys, the on-screen pad, and mission playback post `DRIVE`. The canvas arrow follows encoder pose from `/api/data` while you drive, including during teaching. Teaching records that motion, and repeat mission replays the recorded wheel commands. The CM4 server that implements its routes is `cm4/server`.

On the Pi, `bash cm4/install.sh` installs the apt packages (`python3-flask`, `python3-serial`, `python3-pil`, `python3-usb`) for `/usr/bin/python3` and installs the systemd unit. It does not create a virtualenv. After that, from `cm4/server`:

```bash
python3 server.py --mock-serial --host 127.0.0.1 --port 8080
```

A venv is only for a machine that does not have those apt packages:

```bash
cd cm4/server
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python3 server.py --mock-serial --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080/`. The checklist is [docs/bring-up.md](docs/bring-up.md).

`ESTOP` is sent to the ESP32 as `STOP` and latches until `RESET`. Holding an arrow key or pad button repeats `DRIVE` (PWM 80, a bench duty). Releasing the key, blurring the window, or hiding the page sends a stop, and the server coasts if those posts stop. `/api/data` carries encoder ticks, `batt` from the firmware millivolt field (`batt_calibrated` false until you set it), `dist` from the Kinect when a depth frame exists (otherwise `n/a`), and `odom` from the placeholders. Shutdown stays disabled unless `AMR_ALLOW_POWEROFF=1`. Kinect video uses libfreenect when it returns a frame, and a placeholder JPEG after a camera failure. Tilt and the LED use pyusb on the motor `045e:02b0`, not libfreenect.

Setup, the systemd example, and the field list are in [cm4/server/README.md](cm4/server/README.md). How each page route maps onto the firmware is in [docs/mission-control.md](docs/mission-control.md).

## License

[MIT](LICENSE). Copyright (c) 2026 Vlatko Macak.
