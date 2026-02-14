# Galvable

Control an analog galvanometer over Bluetooth Low Energy using an ESP32-C3 microcontroller.

## Overview

This project turns an ESP32-C3 into a BLE-controlled galvanometer driver. A BLE client writes a floating-point value (0.0 to 1.0) to the device, which translates it into a 10-bit PWM signal on GPIO4 to drive an analog movement galvanometer. The built-in LED (GPIO8) lights up when a client is connected.

A Python client for macOS is included for control from the command line.

## Hardware Requirements

- **ESP32-C3 SuperMini** (or any ESP32-C3 board with USB-C)
- **Analog galvanometer** with current-limiting potentiometer
- USB cable for programming and serial monitoring

### Wiring

```
GPIO4 --> potentiometer (12.5k ohm) --> galvo (+) --> galvo (-) --> GND
```

The potentiometer limits the maximum current through the galvanometer. Adjust it to set the full-scale deflection for a duty value of 1.0.

> **Note:** The ESP32-C3 GPIO can source up to ~40 mA at 3.3V. Most panel-mount galvanometers draw well under this. The potentiometer provides an adjustable safety margin.

## Software Requirements

### Firmware (Arduino)

- [Arduino IDE](https://www.arduino.cc/en/software) or [Arduino CLI](https://arduino.github.io/arduino-cli/)
- **ESP32 board package:** "esp32 by Espressif Systems" v3.x
- **BLE library:** [NimBLE-Arduino](https://github.com/h2zero/NimBLE-Arduino) v2.x by h2zero

### Python Client

- Python 3.8+
- [bleak](https://github.com/hbldh/bleak) BLE library

## Project Structure

```
galvable/
  esp32c3_galvo/
    esp32c3_galvo.ino   Arduino sketch (BLE server + PWM output)
  galvo_client.py       Python BLE client
  README.md             This file
  LICENSE               Apache License 2.0
```

## Arduino Setup

### 1. Install the ESP32 Board Package

**Arduino IDE:**
1. Open **File > Preferences**
2. Add to "Additional Board Manager URLs": `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
3. Open **Tools > Board > Board Manager**, search "esp32", install "esp32 by Espressif Systems" (v3.x)

**Arduino CLI:**
```bash
arduino-cli config add board_manager.additional_urls \
  https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32
```

### 2. Install NimBLE-Arduino

**Arduino IDE:**
1. Open **Sketch > Include Library > Manage Libraries**
2. Search "NimBLE-Arduino", install v2.x by h2zero

**Arduino CLI:**
```bash
arduino-cli lib install "NimBLE-Arduino"
```

### 3. Board Settings

| Setting          | Value              |
|------------------|--------------------|
| Board            | ESP32C3 Dev Module |
| USB CDC On Boot  | Enabled            |
| Upload Speed     | 921600             |
| Flash Mode       | QIO                |
| Partition Scheme | Default 4MB        |

### 4. Compile and Upload

**Arduino IDE:**
1. Open `esp32c3_galvo/esp32c3_galvo.ino`
2. Select the board and port under **Tools**
3. Click **Upload**

**Arduino CLI:**
```bash
arduino-cli compile --fqbn esp32:esp32:esp32c3 esp32c3_galvo/
arduino-cli upload --fqbn esp32:esp32:esp32c3 -p /dev/cu.usbmodem* esp32c3_galvo/
```

### 5. Verify

Open the Serial Monitor at **115200 baud**. You should see:

```
BLE Galvo Controller ... ready!
```

## BLE Protocol

The device advertises with the following BLE profile:

| Field               | Value                                          |
|---------------------|------------------------------------------------|
| Device Name         | `GalvoCtrl`                                    |
| Service UUID        | `e0f3a8b1-4c6d-4e9f-8b2a-7d1c5f3e9a0b`        |
| Characteristic UUID | `a1b2c3d4-5e6f-7890-abcd-ef1234567890`         |
| Property            | Write                                          |

> **Note:** On macOS, the device name may not appear in BLE scans due to advertisement packet size limits. The Python client matches by service UUID as a fallback.

### Data Format

The characteristic accepts a **4-byte little-endian IEEE 754 float**:

| Byte Order    | Type    | Range       | Example (0.5)          |
|---------------|---------|-------------|------------------------|
| Little-endian | float32 | 0.0 - 1.0  | `0x00 0x00 0x00 0x3F`  |

- Values are **clamped** to [0.0, 1.0] on the device
- `NaN` and negative values are treated as 0.0
- Writes with length other than 4 bytes are silently ignored

### PWM Mapping

The float value is mapped to a 10-bit PWM duty cycle (0 to 1000 out of 1023 max) at 5 kHz:

| Float Value | Duty Cycle | Approximate Voltage |
|-------------|------------|---------------------|
| 0.0         | 0          | 0 V                 |
| 0.5         | 500        | ~1.6 V              |
| 1.0         | 1000       | ~3.2 V              |

## Python Client Usage

### Install

```bash
pip install bleak
```

### Single-Shot Mode

Write a single value and disconnect:

```bash
python galvo_client.py 0.75
```

```
Scanning for GalvoCtrl...
Found GalvoCtrl at C5754105-72B8-9486-2E56-F310F115FFE1
Wrote 0.7500
Disconnected.
```

### Interactive Mode

Run without arguments to enter interactive mode. The BLE connection stays open between writes:

```bash
python galvo_client.py
```

```
Scanning for GalvoCtrl...
Found GalvoCtrl at C5754105-72B8-9486-2E56-F310F115FFE1
Enter values 0.0-1.0 (q to quit):
> 0.0
Wrote 0.0000
> 0.5
Wrote 0.5000
> 1.0
Wrote 1.0000
> q
Disconnected.
```

### Debug Mode

Use `--debug` to list all BLE devices found during a full 10-second scan:

```bash
python galvo_client.py --debug
```

This is useful for verifying that the ESP32-C3 is advertising and checking its service UUID.

### Claude Code Gauge Mode

Use `--claudewatch` to keep the BLE connection open and continuously display your Claude Code usage remaining on the galvanometer:

```bash
python galvo_client.py --claudewatch 30
```

This polls the Anthropic usage API every 30 seconds (or whatever interval you specify), inverts the percentage (so the gauge shows *remaining* capacity rather than used), and writes it to the galvo over the persistent BLE connection. A colored progress bar is printed to the terminal on each update.

Requires Claude Code credentials (automatically found in `~/.claude/` or macOS Keychain).

### macOS Bluetooth Permissions

On macOS, your terminal application (Terminal, iTerm2, etc.) needs Bluetooth access. If the script fails to find the device:

1. Open **System Settings > Privacy & Security > Bluetooth**
2. Enable Bluetooth access for your terminal app
3. You may need to restart the terminal after granting permission

## How It Works

### Firmware

1. The ESP32-C3 initializes a NimBLE BLE server with a single writable characteristic
2. PWM is configured on GPIO4 using `ledcAttach()` at 5 kHz, 10-bit resolution
3. The built-in LED (GPIO8, active low) turns on when a client connects
4. When a client writes 4 bytes to the characteristic:
   - The bytes are decoded as a little-endian IEEE 754 float via `memcpy`
   - The value is clamped to [0.0, 1.0] with `NaN` protection
   - The float is scaled to a duty cycle: `duty = (int)(value * 1000.0)`
   - `ledcWrite()` outputs the PWM signal on GPIO4
5. The galvanometer needle deflects proportionally to the duty cycle
6. After disconnect, the LED turns off and the device re-advertises

### Python Client

1. Uses an async BLE scanner with a detection callback for fast discovery (returns immediately when device is found, rather than waiting for the full scan timeout)
2. Matches the device by name (`GalvoCtrl`) or advertised service UUID
3. Encodes the float value as 4 bytes using `struct.pack('<f', value)`
4. Passes the `BLEDevice` object directly to `BleakClient` for reliable connection on macOS

## Known Issues

- **NimBLE-Arduino + Arduino ESP32 core 3.x:** The Arduino core releases BLE controller memory before `setup()` runs unless a BLE library registers itself. NimBLE-Arduino 2.x does not do this automatically. The sketch includes `#include "esp32-hal-bt-mem.h"` as a workaround to prevent a crash during `NimBLEDevice::init()`. See [espressif/arduino-esp32#4243](https://github.com/espressif/arduino-esp32/issues/4243).

- **`analogWriteResolution()` crash:** On ESP32 Arduino core 3.x, calling `analogWriteResolution()` before the first `analogWrite()` can crash due to a null pointer in the LEDC driver. The sketch uses `ledcAttach()` + `ledcWrite()` instead. See [espressif/arduino-esp32#11670](https://github.com/espressif/arduino-esp32/issues/11670).

- **Device name not visible in BLE scan:** The 128-bit service UUID consumes most of the 31-byte BLE advertisement packet, leaving no room for the device name. The Python client falls back to matching by service UUID.

## Debug Mode

Uncomment `#define DEBUG` at the top of the sketch to enable:
- A 2-second boot delay (gives time to open Serial Monitor)
- `Serial.flush()` after each debug print (ensures output is visible before any crash)

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **Guru Meditation crash on boot** | Ensure `#include "esp32-hal-bt-mem.h"` is present. See Known Issues above. |
| **Device not found** | Ensure ESP32-C3 is powered. Use `--debug` flag on the Python client to list all visible BLE devices. Check macOS Bluetooth permissions. |
| **Device found but connection fails** | The ESP32-C3 may still be connected to a previous client. Reset the board or wait for the connection to time out. |
| **Galvo doesn't move** | Verify wiring: GPIO4 -> pot -> galvo+ -> galvo- -> GND. Check Serial Monitor for "Set duty" messages. |
| **Serial Monitor shows nothing** | Enable "USB CDC On Boot" in board settings. Set baud rate to 115200. |
| **Python script errors** | Ensure `bleak` is installed: `pip install bleak`. Python 3.8+ is required. |

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
