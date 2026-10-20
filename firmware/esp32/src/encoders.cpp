#include "encoders.h"

#include "config.h"
#include "pins.h"

#include <Arduino.h>

namespace amr {
namespace {

struct QuadState {
  uint8_t pin_a;
  uint8_t pin_b;
  volatile uint8_t last;
  volatile int32_t count;
};

QuadState g_left{pins::kLeftEncA, pins::kLeftEncB, 0, 0};
QuadState g_right{pins::kRightEncA, pins::kRightEncB, 0, 0};

// prev << 2 | curr. One Gray-code direction increments, the other decrements.
// Both channels are sampled on CHANGE, so one Hall pulse becomes
// kQuadratureMultiplier (4) ticks. Which mechanical direction is positive
// is unset until the encoders are wired.
// DRAM_ATTR so the ISR does not fetch the table from flash.
static_assert(amr::kQuadratureMultiplier == 4,
              "ISR counts one tick per edge on A and B");
static const DRAM_ATTR int8_t kQuadTable[16] = {
    0, -1, 1,  0,
    1, 0,  0,  -1,
    -1, 0, 0,  1,
    0, 1,  -1, 0};

uint8_t IRAM_ATTR sample(const QuadState &enc) {
  return static_cast<uint8_t>(((digitalRead(enc.pin_a) & 1) << 1) |
                               (digitalRead(enc.pin_b) & 1));
}

void IRAM_ATTR decode(QuadState &enc) {
  const uint8_t now = sample(enc);
  const uint8_t index = static_cast<uint8_t>((enc.last << 2) | now);
  enc.count += kQuadTable[index];
  enc.last = now;
}

void IRAM_ATTR onLeft() { decode(g_left); }
void IRAM_ATTR onRight() { decode(g_right); }

int32_t readCount(const QuadState &enc) {
  noInterrupts();
  const int32_t value = enc.count;
  interrupts();
  return value;
}

}  // namespace

void encodersBegin() {
  const int encoder_pins[] = {
      pins::kLeftEncA, pins::kLeftEncB, pins::kRightEncA, pins::kRightEncB};
  for (int pin : encoder_pins) {
    // Internal pull-up to 3.3 V. GPIO 34–39 cannot do this. A stiff
    // external pull-up to the encoder 3.3 V rail is still worth fitting
    // if counts skip. Do not pull these pins up to 5 V.
    pinMode(pin, INPUT_PULLUP);
  }

  g_left.last = sample(g_left);
  g_right.last = sample(g_right);

  attachInterrupt(digitalPinToInterrupt(pins::kLeftEncA), onLeft, CHANGE);
  attachInterrupt(digitalPinToInterrupt(pins::kLeftEncB), onLeft, CHANGE);
  attachInterrupt(digitalPinToInterrupt(pins::kRightEncA), onRight, CHANGE);
  attachInterrupt(digitalPinToInterrupt(pins::kRightEncB), onRight, CHANGE);
}

int32_t encoderLeft() { return readCount(g_left); }
int32_t encoderRight() { return readCount(g_right); }

}  // namespace amr
