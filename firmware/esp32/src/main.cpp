#include <Arduino.h>

#include "config.h"
#include "drive.h"
#include "encoders.h"
#include "pins.h"
#include "protocol.h"

void setup() {
  Serial.begin(amr::kSerialBaud);
  Serial2.begin(amr::kSerialBaud, SERIAL_8N1, amr::pins::kCm4Rx, amr::pins::kCm4Tx);
  amr::driveBegin();
  amr::encodersBegin();
  amr::protocolBegin(Serial, Serial2);
}

void loop() {
  if (amr::drivePollTimeout()) {
    amr::protocolBroadcast("ERR command timeout");
  }
  amr::protocolPoll();
}
