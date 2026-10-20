from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    # CALIBRATE. These match cm4/server/calibration.py and are not measurements.
    # Stop cm4/server before this launch. Both open the same UART.
    return LaunchDescription([
        Node(
            package='amr_base',
            executable='base_driver_node',
            name='base_driver',
            parameters=[{
                # Placeholder path. The CM4 carrier UART device node is unset.
                'serial_port': '/dev/ttyAMA0',
                'baud': 115200,
                'wheel_diameter_m': 0.065,
                'track_width_m': 0.20,
                # 11 Hall pulses * gear ratio 9.6 * quadrature 4. TODO: calibrate.
                'ticks_per_rev': 422.4,
                'left_tick_sign': 1,
                'right_tick_sign': 1,
                # 1 m/s would request PWM 400, then the node clamps to 255.
                'pwm_per_mps': 400.0,
                'geometry_calibrated': False,
                'cmd_timeout_s': 0.3,
                'drive_repeat_s': 0.2,
                'odom_frame': 'odom',
                'base_frame': 'base_link',
            }],
        ),
        Node(
            package='amr_base',
            executable='kinect_freenect_node',
            name='kinect_freenect',
            parameters=[{
                'frame_id': 'kinect_link',
            }],
        ),
    ])
