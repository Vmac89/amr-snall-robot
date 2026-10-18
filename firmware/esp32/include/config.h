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

}  // namespace amr
