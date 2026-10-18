# amr_base

Placeholder ROS 2 package for the Raspberry Pi CM4. The distribution is not chosen. libfreenect is not a dependency yet.

| Node | Role in this scaffold |
| --- | --- |
| `base_driver_node` | Subscribes to `cmd_vel`, advertises `odom`. Does not open the ESP32 serial port and does not publish odometry. |
| `kinect_freenect_node` | Advertises `kinect/image_raw`, `kinect/depth`, and `kinect/camera_info`. Publishes no frames. |

The ESP32 line protocol the bridge will speak is [docs/serial-protocol.md](../../../docs/serial-protocol.md). `serial_port` defaults to `/dev/ttyAMA0`, which is only a placeholder until the carrier UART is identified. The Kinect model string supplied for this robot is `1505`.

When a ROS 2 distro is installed on the build machine:

```bash
cd ros2_ws
source /opt/ros/<distro>/setup.bash
colcon build --packages-select amr_base
```
