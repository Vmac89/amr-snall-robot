# ESP32 firmware

PlatformIO project for the ESP32 DevKit V1. It drives two motors through an L298N, counts quadrature encoder edges, and speaks the serial protocol in [docs/serial-protocol.md](../../docs/serial-protocol.md).

GPIO numbers are the proposed map in [hardware/electronics/pinout.md](../../hardware/electronics/pinout.md).

## Build

From the repository root:

```bash
pio run -d firmware/esp32
```

From this directory: `pio run`.

The `esp32dev` environment pins the official PlatformIO `espressif32` platform at 7.1.3, which packages Arduino-ESP32 2.0.17. PWM setup uses `ledcSetup` and `ledcAttachPin` from that core.

`pio run -t upload` flashes a DevKit on USB. The environment does not pick an upload port.
