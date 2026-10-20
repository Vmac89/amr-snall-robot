# ESP32 firmware

PlatformIO project for the ESP32 DevKit V4 (same pinout as V1). It drives two JGA25-371 motors through an L298N, counts quadrature encoder edges, and speaks the serial protocol in [docs/serial-protocol.md](../../docs/serial-protocol.md).

Hall A/B use GPIO 18/19 (left) and GPIO 21/22 (right), with internal pull-ups. Expected ticks per wheel revolution are `kHallPulsesPerMotorRev * kGearRatio * kQuadratureMultiplier` in `include/config.h` (`11 * 9.6 * 4`). `kGearRatio` is a TODO until the 10-turn count in the bring-up checklist. The firmware still reports raw ticks; it does not divide by that constant.

GPIO numbers are the proposed map in [hardware/electronics/pinout.md](../../hardware/electronics/pinout.md). `ENC` lines include battery millivolts from GPIO 4 times `kBatteryDividerRatio` (`1.0` until you measure the divider).

## Build

From the repository root:

```bash
pio run -d firmware/esp32
```

From this directory: `pio run`.

The `esp32dev` environment pins the official PlatformIO `espressif32` platform at 7.1.3, which packages Arduino-ESP32 2.0.17. PWM setup uses `ledcSetup` and `ledcAttachPin` from that core.

`pio run -t upload` flashes a DevKit on USB. The environment does not pick an upload port.
