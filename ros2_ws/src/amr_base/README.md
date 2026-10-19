# amr_base

ROS 2 package for the Raspberry Pi CM4. The distribution is not chosen, and this package was not built in the environment that added the bridge. `colcon` is expected to compile it once a distro and `tf2_ros` are installed.

| Node | Role |
| --- | --- |
| `base_driver_node` | Opens the ESP32 UART, turns `cmd_vel` into `DRIVE` / `STOP`, and publishes `odom` plus a tf from `odom` to `base_link` from `ENC` ticks. |
| `kinect_freenect_node` | Publishes `kinect/image_raw`, `kinect/depth`, and `kinect/camera_info` when libfreenect was found at build time. Otherwise it advertises the topics and stays quiet. |

Do not run `base_driver_node` while `cm4/server` is running. Both open the UART.

The line protocol is [docs/serial-protocol.md](../../../docs/serial-protocol.md). `serial_port` defaults to `/dev/ttyAMA0`, a placeholder until the carrier UART is identified. Baud in the node is 115200 to match the firmware; the `baud` parameter is recorded and not applied to other rates.

Geometry and the `cmd_vel` gain are the same placeholders as `cm4/server/calibration.py`:

| Parameter | Placeholder | Meaning |
| --- | --- | --- |
| `wheel_diameter_m` | `0.065` | CALIBRATE |
| `track_width_m` | `0.20` | CALIBRATE |
| `ticks_per_rev` | `360` | CALIBRATE, one wheel revolution |
| `left_tick_sign`, `right_tick_sign` | `1` | CALIBRATE, set `-1` if that wheel counts backward while rolling forward |
| `pwm_per_mps` | `400` | CALIBRATE. Not a measured top speed. Values above 255 clamp. |
| `geometry_calibrated` | `false` | Set true only after the numbers above were measured |

`cmd_vel` is mixed as `v_left = linear.x - angular.z * track / 2` and the same with a plus for the right wheel, then multiplied by `pwm_per_mps`. A fresh command is repeated about every 0.2 s so the firmware 500 ms timeout does not coast. If `cmd_vel` stops for `cmd_timeout_s` (0.3 s), the node sends `STOP`.

Camera intrinsics are zeros. The Kinect is model `1414`, the Xbox 360 Kinect (v1). CMake defines `AMR_HAS_FREENECT` only when `libfreenect/libfreenect.h` and `libfreenect` are both found. The Bookworm apt package did not open this sensor; the source build is in [docs/bring-up.md](../../../docs/bring-up.md).

When a ROS 2 distro is installed on the build machine:

```bash
cd ros2_ws
source /opt/ros/<distro>/setup.bash
colcon build --packages-select amr_base
source install/setup.bash
ros2 launch amr_base bringup.launch.py
```
