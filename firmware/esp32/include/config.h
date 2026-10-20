#pragma once

#include <stdint.h>

namespace amr {

constexpr uint32_t kSerialBaud = 115200;
constexpr uint32_t kPwmFrequencyHz = 1000;
constexpr uint8_t kPwmResolutionBits = 8;
constexpr uint32_t kCommandTimeoutMs = 500;
constexpr uint32_t kTelemetryPeriodMs = 100;
constexpr int kWheelCommandMin = -255;
constexpr int kWheelCommandMax = 255;

// CALIBRATE. Pack volts = ADC pin volts * this ratio, where
// ratio = (R_top + R_bottom) / R_bottom and R_top is the resistor on the
// pack side. Placeholder 1.0 reports the pin voltage only. Do not treat
// it as the 12 V pack until the divider you fitted is entered here.
constexpr float kBatteryDividerRatio = 1.0f;

// JGA25-371 Hall encoder. 11 pulses leave the motor shaft per revolution.
// The firmware decoder in encoders.cpp counts one tick on every edge of
// both channels, so the quadrature multiplier is 4.
// TODO: calibrate GEAR_RATIO. 9.6 is the ratio quoted for the 1000 RPM
// output (motor-shaft turns per wheel turn). It has not been counted on
// these motors. kTicksPerWheelRev must stay equal to the product, and to
// TICKS_PER_REV in cm4/server/calibration.py.
constexpr int kHallPulsesPerMotorRev = 11;
constexpr double kGearRatio = 9.6;
constexpr int kQuadratureMultiplier = 4;
constexpr double kTicksPerWheelRev =
    kHallPulsesPerMotorRev * kGearRatio * kQuadratureMultiplier;
static_assert(kTicksPerWheelRev > 422.0 && kTicksPerWheelRev < 422.5,
              "11 * 9.6 * 4 must stay the uncalibrated ticks-per-wheel-rev");

}  // namespace amr
