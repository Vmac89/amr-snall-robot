#include "protocol.h"

#include "config.h"
#include "drive.h"
#include "encoders.h"

#include <Arduino.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace amr {
namespace {

constexpr size_t kMaxLine = 64;
constexpr int kMaxLinesPerPoll = 8;

enum class LineEvent { kNone, kLine, kOverflow };

struct PortState {
  HardwareSerial *port;
  char buf[kMaxLine];
  size_t len;
  bool overflow;
  bool telem;
};

PortState g_ports[2];
uint32_t g_last_telem_ms = 0;

void reply(PortState &ps, const char *text) { ps.port->println(text); }

void emitEncoders(HardwareSerial &port) {
  char line[48];
  std::snprintf(line, sizeof line, "ENC %ld %ld",
                static_cast<long>(encoderLeft()),
                static_cast<long>(encoderRight()));
  port.println(line);
}

bool parseInt(const char *&cursor, long &value) {
  if (*cursor == '\0') {
    return false;
  }
  char *end = nullptr;
  const long parsed = std::strtol(cursor, &end, 10);
  if (end == cursor) {
    return false;
  }
  cursor = end;
  while (*cursor == ' ') {
    ++cursor;
  }
  value = parsed;
  return true;
}

void handleLine(PortState &ps, char *line) {
  char *cmd = line;
  while (*cmd == ' ') {
    ++cmd;
  }
  if (*cmd == '\0') {
    return;
  }

  char *args = cmd;
  while (*args != '\0' && *args != ' ') {
    ++args;
  }
  if (*args != '\0') {
    *args = '\0';
    ++args;
    while (*args == ' ') {
      ++args;
    }
  }

  if (std::strcmp(cmd, "HELP") == 0) {
    if (*args != '\0') {
      reply(ps, "ERR unexpected arguments");
      return;
    }
    driveNoteHeartbeat();
    reply(ps, "OK HELP PING STOP DRIVE ENC TELEM");
    return;
  }

  if (std::strcmp(cmd, "PING") == 0) {
    if (*args != '\0') {
      reply(ps, "ERR unexpected arguments");
      return;
    }
    driveNoteHeartbeat();
    reply(ps, "PONG");
    return;
  }

  if (std::strcmp(cmd, "STOP") == 0) {
    if (*args != '\0') {
      reply(ps, "ERR unexpected arguments");
      return;
    }
    driveNoteHeartbeat();
    driveCoast();
    reply(ps, "OK");
    return;
  }

  if (std::strcmp(cmd, "DRIVE") == 0) {
    const char *cursor = args;
    long left = 0;
    long right = 0;
    if (!parseInt(cursor, left) || !parseInt(cursor, right) || *cursor != '\0') {
      reply(ps, "ERR expected DRIVE <left> <right>");
      return;
    }
    if (left < kWheelCommandMin || left > kWheelCommandMax ||
        right < kWheelCommandMin || right > kWheelCommandMax) {
      reply(ps, "ERR value out of range");
      return;
    }
    driveNoteHeartbeat();
    driveSet(static_cast<int>(left), static_cast<int>(right));
    reply(ps, "OK");
    return;
  }

  if (std::strcmp(cmd, "ENC") == 0) {
    if (*args != '\0') {
      reply(ps, "ERR unexpected arguments");
      return;
    }
    driveNoteHeartbeat();
    emitEncoders(*ps.port);
    return;
  }

  if (std::strcmp(cmd, "TELEM") == 0) {
    const char *cursor = args;
    long enable = 0;
    if (!parseInt(cursor, enable) || *cursor != '\0' ||
        (enable != 0 && enable != 1)) {
      reply(ps, "ERR expected TELEM 0 or 1");
      return;
    }
    ps.telem = (enable == 1);
    driveNoteHeartbeat();
    reply(ps, "OK");
    return;
  }

  reply(ps, "ERR unknown command");
}

LineEvent pollPort(PortState &ps, char *out, size_t out_cap) {
  while (ps.port->available() > 0) {
    const int raw = ps.port->read();
    if (raw < 0) {
      break;
    }
    const char c = static_cast<char>(raw);
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      if (ps.overflow) {
        ps.overflow = false;
        ps.len = 0;
        return LineEvent::kOverflow;
      }
      if (ps.len >= out_cap) {
        ps.len = 0;
        return LineEvent::kOverflow;
      }
      std::memcpy(out, ps.buf, ps.len);
      out[ps.len] = '\0';
      ps.len = 0;
      return LineEvent::kLine;
    }
    if (ps.overflow || ps.len + 1 >= sizeof ps.buf) {
      ps.overflow = true;
      ps.len = 0;
      continue;
    }
    ps.buf[ps.len++] = c;
  }
  return LineEvent::kNone;
}

}  // namespace

void protocolBegin(HardwareSerial &usb, HardwareSerial &cm4) {
  g_ports[0] = PortState{&usb, {}, 0, false, false};
  g_ports[1] = PortState{&cm4, {}, 0, false, false};
  g_last_telem_ms = millis();
  usb.println("READY");
  cm4.println("READY");
}

void protocolPoll() {
  char line[kMaxLine];
  for (PortState &ps : g_ports) {
    for (int n = 0; n < kMaxLinesPerPoll; ++n) {
      const LineEvent event = pollPort(ps, line, sizeof line);
      if (event == LineEvent::kNone) {
        break;
      }
      if (event == LineEvent::kOverflow) {
        reply(ps, "ERR line too long");
        continue;
      }
      handleLine(ps, line);
    }
  }

  const uint32_t now = millis();
  if (now - g_last_telem_ms < kTelemetryPeriodMs) {
    return;
  }
  g_last_telem_ms = now;
  for (PortState &ps : g_ports) {
    if (ps.telem) {
      emitEncoders(*ps.port);
    }
  }
}

void protocolBroadcast(const char *line) {
  for (PortState &ps : g_ports) {
    ps.port->println(line);
  }
}

}  // namespace amr
