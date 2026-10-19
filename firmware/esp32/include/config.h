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

}  // namespace amr
