# Bring-up and test checklist

Do these in order, on the bench, with the robot where a wheel can spin without moving the chassis until the direction test says otherwise. Nothing in this list has been measured on this robot. Values marked CALIBRATE are the placeholders in `cm4/server/calibration.py` and `firmware/esp32/include/config.h`.

Stop `cm4/server` before starting the ROS 2 base driver, and the other way around. Both open the UART.

## 1. Wiring, motors unplugged from the L298N outputs

- Common ground: battery negative, buck ground, L298N ground, ESP32 ground, CM4 ground.
- Meter the buck before it touches the CM4 carrier or the ESP32. The required carrier input is unset. The DevKit is powered from USB or its 5 V pin. The 3V3 pin is an output.
- Confirm the JGA25-370 nameplate voltage before the pack lands on the L298N motor supply.
- Remove the L298N `ENA` and `ENB` jumpers. ESP32 PWM drives those pins.
- ESP32 GPIO high is 3.3 V. Confirm that is a valid high for this L298N, or level-shift the six control lines.
- Encoder leads: proposed inputs are GPIO 34, 35, 36, and 39. Those pins have no internal pull-ups. Meter the encoder high before it touches a GPIO. A 5 V swing can damage the ESP32.
- UART: ESP32 GPIO 17 TX to the CM4 RX, GPIO 16 RX to the CM4 TX, shared ground, 3.3 V both ends. The Linux device node is unset. `/dev/ttyAMA0` is only the placeholder.
- Leave strapping pins (GPIO 0, 2, 12, 15), UART0 (GPIO 1 and 3), and flash pins (GPIO 6–11) out of the harness.
- Fuse the motor supply. Stall current is unset.

### Battery divider

Proposed sense pin is GPIO 4 (`kBatteryAdc`). It is ADC2. WiFi is unused in this firmware; ADC2 is a poor choice if the radio is later turned on.

Do not connect the pack to GPIO 4. Build a divider: pack positive, resistor to the GPIO node, resistor from that node to ground. Meter the GPIO node with the pack connected and the ESP32 pin still disconnected. It must stay inside the pin's range (the firmware attenuation is the nominal ~0–3.3 V setting, not a measured full-scale). Only then land the node on GPIO 4.

`kBatteryDividerRatio` in `firmware/esp32/include/config.h` is `1.0`. That reports pin volts, not pack volts. Set it to `(R_top + R_bottom) / R_bottom` after you choose resistors. No resistor values are specified here. Leave `AMR_BATT_CALIBRATED` unset until a meter on the pack agrees with `batt` on `/api/data`.

## 2. Flash the ESP32

From a machine with PlatformIO and the DevKit on USB:

```bash
pio run -t upload -d firmware/esp32
pio device monitor -d firmware/esp32 -b 115200
```

You should see `READY`. Then, on that monitor:

```
PING
ENC
TELEM 1
```

Expect `PONG`, then `ENC <left> <right> <battery_mv>`. With the divider ratio still `1.0`, `battery_mv` is pin millivolts (about 0 if the pin is floating). Spin each wheel by hand and confirm the matching tick count changes. Swapping the two channels of one encoder flips its sign.

## 3. CM4 install

This robot's host is a Waveshare CM4-Duino running Raspberry Pi OS Lite (Bookworm). On the CM4, from a login user (not as root):

```bash
bash cm4/install.sh
```

The script installs `python3-flask`, `python3-serial`, `python3-pil`, and `python3-usb` for `/usr/bin/python3`, adds your user to `dialout`, and installs the systemd unit with your user and this repo path. It does not create a Python virtualenv, so `cm4/server/.venv/bin/activate` will not exist afterwards. Run the server with `python3 server.py` from `cm4/server`, or with the systemd unit. A venv is a separate option, documented in `cm4/server/README.md`, for a machine that does not use those apt packages. The script does not set `AMR_ALLOW_POWEROFF`. It does not edit the boot config. Confirm `enable_uart=1` yourself, then reboot so the group and the UART come up.

Edit `AMR_SERIAL_PORT` in the unit if the carrier is not `/dev/ttyAMA0`. Restart:

```bash
sudo systemctl restart amr-mission-control.service
```

`GET /api/data` should show `serial_connected: true` once the ESP32 answers. If the port is missing, HTTP still serves and `serial_connected` stays false. The server does not fall back to mock mode in that case.

## 4. Motor direction, wheels off the ground

Open Mission Control (`http://<cm4>:8080/`). Hold the on-screen forward button, or hold Arrow Up. Both wheels should roll the robot's forward direction. PWM while held is `DRIVE_PWM` 80 in the page (CALIBRATE, a bench duty, not a speed).

- A wheel that spins backward: swap that motor's two leads at the L298N, or swap the firmware direction pins for that side. Do one, then re-test.
- Releasing the key, leaving the tab, or hiding the page must coast the wheels within about half a second (server watchdog) and the firmware coasts on its own if commands stop for 500 ms.
- Emergency stop latches. Further drive commands are rejected until RESET ESTOP.
- Arrow keys while a text field is focused must not drive.

## 5. Encoder sign, ticks per revolution, diameter, track

With the wheels still unloaded, or with the chassis rolled a known distance:

1. Roll one wheel one revolution with the other held. The tick delta is `ticks_per_rev` for that wheel. The placeholder is `360`. Put the measured count in `AMR_TICKS_PER_REV` and in the ROS parameter of the same name.
2. If a wheel's count decreases while the robot rolls forward, set that side's `AMR_LEFT_TICK_SIGN` or `AMR_RIGHT_TICK_SIGN` to `-1`.
3. Measure the wheel diameter and the distance between the two contact patches. Placeholders are `0.065` m and `0.20` m (`AMR_WHEEL_DIAMETER_M`, `AMR_TRACK_WIDTH_M`).
4. Roll straight a measured distance and compare with `odom.x` on `/api/data`. Adjust diameter, then ticks, until it agrees. Then set `AMR_GEOMETRY_CALIBRATED=1`. Until that flag is set, `odom.calibrated` stays false even though a pose is still computed from the placeholders.

## 6. Kinect (model 1414)

The sensor is the original Xbox 360 Kinect, model `1414` (Kinect v1). Plug its USB into the CM4 and power it from its own 12 V adapter. The CM4 USB port does not power this sensor.

`cm4/install.sh` does not install libfreenect. On this Bookworm image, apt `libfreenect` 0.5.3 fails in the depth path with `Failed to fetch zero plane info`. Build the library from the OpenKinect git tree instead. The CMake Python option fails with `list GET given empty list`, so leave Python out of that build and install the wrapper with `setup.py`.

```bash
sudo apt-get install -y cmake build-essential libusb-1.0-0-dev python3-dev python3-setuptools
git clone https://github.com/OpenKinect/libfreenect.git
cd libfreenect
mkdir build && cd build
cmake .. -DBUILD_PYTHON3=OFF
make
sudo make install
sudo ldconfig
cd ../wrappers/python
sudo python3 setup.py install
sudo install -m 644 ../../platform/linux/udev/51-kinect.rules /etc/udev/rules.d/51-kinect.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

`51-kinect.rules` allows non-root access to the Kinect motor, USB `045e:02b0`. That is the device Mission Control tilts. The camera is a different USB product and is the only part that uses libfreenect.

Tilt and the LED do not go through libfreenect. On this CM4 the camera fails in libfreenect with `Failed to fetch const shift`, and `freenect.open_device` followed by a tilt call segfaults. `cm4/server` keeps libfreenect for video only. `python3-usb` (installed by `cm4/install.sh`) sends the motor transfers that were tested on this unit: tilt is `ctrl_transfer(0x40, 0x31, (deg * 2) & 0xFFFF, 0, b'')` with `deg` clamped to −30..30, and the LED is `ctrl_transfer(0x40, 0x06, led, 0, b'')` where `1` is green. The page's tilt buttons call `GET /tilt/up` and `GET /tilt/down`. `POST /api/led?value=1` sets that green LED; the page does not call it. If the camera raises, the process stays up, it does not call freenect tilt, and `/video_feed` keeps serving the placeholder JPEG. `applied` on the tilt JSON is false when the motor is missing or the transfer fails. The page still logs "Tilt success" because it only prints `angle`.

USB autosuspend has to be off or the Kinect drops off the bus. A setting that stays across reboot is `usbcore.autosuspend=-1` at the end of the single line in `/boot/firmware/cmdline.txt`. Reboot after editing that file.

`otg_mode=1` under the `[cm4]` section of `/boot/firmware/config.txt` is the USB-host line tried on this Waveshare CM4-Duino. It is still being verified. This repo does not write that file. A wrong boot overlay can keep the board from booting, so confirm the line before relying on it, and do not treat a missing camera as a finished library build until that check is done.

With the source-built libfreenect importing and the camera returning a frame, `/api/data` field `dist` becomes centimetres from the center of the depth frame, and `kinect_live` can become true. `dist_calibrated` stays false. Check a few known gaps with a tape before trusting `dist`. If the camera does not face forward, the center window is the wrong obstacle. The `Failed to fetch const shift` failure leaves `dist` at `n/a` and the video on the placeholder; tilt still uses the motor.

`AMR_OBSTACLE_CM` defaults to `40` (CALIBRATE). When `dist` is a number below that threshold, forward wheel commands are forced to zero and reverse is still allowed. A missing distance does not block motion. Set `AMR_OBSTACLE_CALIBRATED=1` only after the tape check. The flag is reported; it does not by itself change the threshold.

Fallback if the Mission Control camera path stays down: `cm4/server/legacy_streamer.py` is the earlier streamer that worked on this Kinect. It is a reference only. `server.py` does not import it. It opens the device once with the libfreenect async API and shares that handle for video and tilt, writes JPEGs to `/dev/shm/kinect.jpg`, and reads `/dev/shm/tilt_cmd.txt` (`up` or `down`). From `cm4/server`, with the source-built freenect module and OpenCV installed:

```bash
sudo python3 legacy_streamer.py
```

The file still prints `streamer.py` in its root check; the path in this repo is `legacy_streamer.py`. Stop `amr-mission-control.service` first so the two programs do not both open the Kinect. Writing `up` or `down` into `/dev/shm/tilt_cmd.txt` steps the tilt by 3 degrees, clamped to ±30.

## 7. First drive

Wheels on the ground, a clear lane, a hand on ESTOP.

1. Tap forward and release. The robot should start and then coast when you release.
2. Confirm left and right spins match the pad.
3. Teach a short path, then REPEAT MISSION. Playback repeats the recorded wheel commands from the current pose and then stops. A station under the marker pauses the timeline.
4. Cover or approach an obstacle inside the threshold and confirm forward motion stops while reverse still works.
5. Press ESTOP and confirm drive stays rejected until RESET.

Shutdown stays disabled. Arming `AMR_ALLOW_POWEROFF=1` really runs `shutdown -h now` on the CM4.

## ROS 2, after the web path works

The ROS 2 distro is not chosen. Build steps are in `ros2_ws/src/amr_base/README.md`. Use the same measured geometry. `pwm_per_mps` is `400` (CALIBRATE). Stop the web server first so it releases the UART.
