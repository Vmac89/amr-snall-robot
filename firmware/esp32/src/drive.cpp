#include "drive.h"

#include "config.h"
#include "pins.h"

#include <Arduino.h>

namespace amr {
namespace {

bool g_motion = false;
uint32_t g_last_heartbeat_ms = 0;

int clampCommand(int command) {
  if (command < kWheelCommandMin) {
    return kWheelCommandMin;
  }
  if (command > kWheelCommandMax) {
    return kWheelCommandMax;
  }
  return command;
}

// Both direction inputs low and PWM at 0 coasts the motor.
void writeWheel(int in_a, int in_b, int pwm_channel, int command) {
  command = clampCommand(command);
  if (command > 0) {
    digitalWrite(in_a, HIGH);
    digitalWrite(in_b, LOW);
  } else if (command < 0) {
    digitalWrite(in_a, LOW);
    digitalWrite(in_b, HIGH);
  } else {
    digitalWrite(in_a, LOW);
    digitalWrite(in_b, LOW);
  }
  const int magnitude = command < 0 ? -command : command;
  ledcWrite(static_cast<uint8_t>(pwm_channel), static_cast<uint32_t>(magnitude));
}

}  // namespace

void driveBegin() {
  const int outputs[] = {
      pins::kLeftIn1, pins::kLeftIn2, pins::kRightIn3, pins::kRightIn4};
  for (int pin : outputs) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }

  ledcSetup(pins::kLeftPwmChannel, kPwmFrequencyHz, kPwmResolutionBits);
  ledcAttachPin(pins::kLeftEn, pins::kLeftPwmChannel);
  ledcSetup(pins::kRightPwmChannel, kPwmFrequencyHz, kPwmResolutionBits);
  ledcAttachPin(pins::kRightEn, pins::kRightPwmChannel);
  ledcWrite(pins::kLeftPwmChannel, 0);
  ledcWrite(pins::kRightPwmChannel, 0);

  g_last_heartbeat_ms = millis();
  g_motion = false;
}

void driveCoast() {
  writeWheel(pins::kLeftIn1, pins::kLeftIn2, pins::kLeftPwmChannel, 0);
  writeWheel(pins::kRightIn3, pins::kRightIn4, pins::kRightPwmChannel, 0);
  g_motion = false;
}

void driveSet(int left, int right) {
  writeWheel(pins::kLeftIn1, pins::kLeftIn2, pins::kLeftPwmChannel, left);
  writeWheel(pins::kRightIn3, pins::kRightIn4, pins::kRightPwmChannel, right);
  g_motion = (left != 0 || right != 0);
}

void driveNoteHeartbeat() { g_last_heartbeat_ms = millis(); }

bool drivePollTimeout() {
  if (!g_motion) {
    return false;
  }
  if (millis() - g_last_heartbeat_ms < kCommandTimeoutMs) {
    return false;
  }
  driveCoast();
  return true;
}

}  // namespace amr
