#pragma once

// Proposed ESP32 DevKit V1 assignment. Keep this file in sync with
// hardware/electronics/pinout.md. These are not measured connections.

namespace amr {
namespace pins {

constexpr int kLeftEn = 25;
constexpr int kLeftIn1 = 26;
constexpr int kLeftIn2 = 27;

constexpr int kRightEn = 14;
constexpr int kRightIn3 = 32;
constexpr int kRightIn4 = 33;

constexpr int kLeftEncA = 34;
constexpr int kLeftEncB = 35;
constexpr int kRightEncA = 36;
constexpr int kRightEncB = 39;

// UART2 defaults on the Arduino DevKit map: RX2 = 16, TX2 = 17.
constexpr int kCm4Rx = 16;
constexpr int kCm4Tx = 17;

constexpr int kLeftPwmChannel = 0;
constexpr int kRightPwmChannel = 1;

}  // namespace pins
}  // namespace amr
