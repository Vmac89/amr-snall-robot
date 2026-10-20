#pragma once

#include <Arduino.h>

namespace amr {

void protocolBegin(HardwareSerial &usb, HardwareSerial &cm4);
void protocolPoll();
void protocolBroadcast(const char *line);

}  // namespace amr
