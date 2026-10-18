from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='amr_base',
            executable='base_driver_node',
            name='base_driver',
            parameters=[{
                # Placeholder path. The CM4 carrier UART device node is unset.
                'serial_port': '/dev/ttyAMA0',
                'baud': 115200,
            }],
        ),
        Node(
            package='amr_base',
            executable='kinect_freenect_node',
            name='kinect_freenect',
        ),
    ])
