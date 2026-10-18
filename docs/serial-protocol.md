# ESP32 serial protocol

The firmware in `firmware/esp32` speaks this protocol on two ports at **115200 8N1**:

- USB serial (UART0 through the DevKit's USB-UART bridge), for a bench PC.
- UART2 (GPIO 16 RX, GPIO 17 TX), the intended link to the Raspberry Pi CM4.

Both ports accept the same commands. A command on either port is a heartbeat for the motor timeout.

Lines end in `\n` or `\r\n`. Commands are case-sensitive. There is no checksum; this is a bring-up protocol.

On boot, each port prints one line:

```
READY
```

## Commands

| Command | Response | Effect |
| --- | --- | --- |
| `HELP` | `OK HELP PING STOP DRIVE ENC TELEM` | Lists the command names. |
| `PING` | `PONG` | Heartbeat only. |
| `STOP` | `OK` | Coast both motors (enable PWM 0, both direction inputs low). |
| `DRIVE <left> <right>` | `OK` | Wheel commands, integers from `-255` to `255`. Positive is the firmware direction; swap motor leads if the wheel turns the wrong way. |
| `ENC` | `ENC <left_ticks> <right_ticks>` | Signed cumulative quadrature counts. |
| `TELEM <0\|1>` | `OK` | `1` prints an `ENC` line on that port every 100 ms. `0` stops it. |

Every well-formed command refreshes the motion heartbeat, including `ENC` and `PING`. Telemetry lines the firmware prints do not count as a heartbeat. While a non-zero `DRIVE` is active, some valid command must arrive at least every 500 ms (`kCommandTimeoutMs` in `firmware/esp32/include/config.h`). When the window expires the firmware coasts the motors and prints this unsolicited line on both ports:

```
ERR command timeout
```

## Errors

| Line | When |
| --- | --- |
| `ERR unknown command` | First word is not a command. |
| `ERR unexpected arguments` | `HELP`, `PING`, `STOP`, or `ENC` had extra tokens. |
| `ERR expected DRIVE <left> <right>` | `DRIVE` could not be parsed as two integers. |
| `ERR value out of range` | A wheel command was outside `-255`..`255`. |
| `ERR expected TELEM 0 or 1` | `TELEM` was not exactly `0` or `1`. |
| `ERR line too long` | The line exceeded 63 characters and was discarded. |

Empty lines are ignored.

## Example

```
PING
PONG
DRIVE 80 -40
OK
ENC
ENC 0 0
TELEM 1
OK
ENC 12 -3
TELEM 0
OK
STOP
OK
```

Tick sign follows the quadrature decode in `firmware/esp32/src/encoders.cpp`. Which mechanical direction increments a count is unset until the encoder wiring is checked. One encoder channel swapped with the other flips the sign.

Wheel mixing from `cmd_vel` is intentionally not in this protocol. The CM4 sends per-wheel commands after it has a measured wheel radius and track width.
