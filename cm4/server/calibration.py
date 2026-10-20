"""Placeholders for values that have not been measured on this robot.

Every number in this file is a starting point for bench calibration.
None of them is a measurement of the chassis, the pack, the encoders, or
the Kinect mount. The ROS 2 parameters in ros2_ws/src/amr_base use the
same placeholders.
"""

from __future__ import annotations

# Wheel diameter in metres. CALIBRATE with a ruler or from the CAD model.
WHEEL_DIAMETER_M = 0.065

# Distance between the two wheel contact patches, in metres. CALIBRATE.
TRACK_WIDTH_M = 0.20

# JGA25-371 Hall encoder. 11 pulses per motor-shaft revolution.
# The firmware counts every edge of both channels (see encoders.cpp).
ENCODER_PULSES_PER_MOTOR_REV = 11
QUADRATURE_MULTIPLIER = 4
# TODO: calibrate. Motor-shaft turns per wheel turn. 9.6 is the ratio
# quoted for the 1000 RPM output. It has not been counted on these motors.
GEAR_RATIO = 9.6
# Counts for one wheel revolution after the firmware decoder.
# 11 * 9.6 * 4 = 422.4 until the 10-turn check in docs/bring-up.md replaces it.
TICKS_PER_REV = ENCODER_PULSES_PER_MOTOR_REV * GEAR_RATIO * QUADRATURE_MULTIPLIER

# Multiply a wheel's tick delta by this before odometry. CALIBRATE: set the
# side to -1 if that wheel counts backward when the robot rolls forward.
LEFT_TICK_SIGN = 1
RIGHT_TICK_SIGN = 1

# PWM counts the page sends while a drive control is held. The server does
# not use this constant; it lives here so the bring-up doc and the page
# comment name the same bench starting duty. Not a measured speed.
PAGE_DRIVE_PWM = 80

# Client must repeat DRIVE faster than this or the server coasts the motors.
# The page repeats at 150 ms. The firmware itself coasts after 500 ms.
CLIENT_WATCHDOG_S = 0.5

# Forward motion is blocked when a Kinect center-window distance is below
# this many centimetres. CALIBRATE after the depth scale is checked.
# Obstacle stop stays inactive while the distance is unavailable.
OBSTACLE_STOP_CM = 40.0

# cmd_vel metres/second times this gain becomes a PWM command in the ROS
# node. CALIBRATE. 1 m/s would request 400 and then the firmware clamps
# at 255, so this is not a measured top speed.
PWM_PER_MPS = 400.0
