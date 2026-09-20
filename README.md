# Galvable / Retrometer

[![Open Source Hardware](https://img.shields.io/badge/Open_Source-Hardware-00979D)](https://oshwa.org/definition/)

The canonical project lives in `esp32_ble_ota_base/sketches/galvable`.
It contains the BLE galvanometer firmware, Python clients, Retrometer website,
and physical faceplate/reference files. Git history and the GitHub remote are
preserved from `joshu017/galvable` (baseline `f3f8420`).

## Layout

- `galvable/galvable.ino`: existing BLE OTA firmware, including persistent device names.
- `Makefile`: local ESP32-C3 build, USB upload and BLE OTA commands.
- `lib/BleOta/`, `scripts/ble_ota_upload.py`: preserved OTA support.
- `galvo_client.py`: unchanged checked-in client, including Claude usage polling.
- `retrometer/retrometer.py`: working Mercury tracker and optional BLE output.
- `retrometer/*.svg`, `*.pdf`: faceplate and cutting artwork.
- `retrometer/reference/mercury2000.pdf`: source ephemeris from the separate folder.
- `retrometer/web/public/index.html`: canonical website source, matching the live page at migration.
- `retrometer/web/`: Cloudflare Workers scaffold, following Ringbeacon's structure.
- `AGENTS.md`: contributor and agent instructions.

## Firmware

ESP32-C3 only. Run the local Makefile from this project directory:

```sh
make help
make setup                         # install pinned core and NimBLE, if needed
make build                         # compile only
make ports
make flash UPLOAD_PORT=/dev/cu.usbmodem...  # explicit USB target
make ble BLE_DEVICE_ADDRESS=<device-address>  # explicit OTA target
make monitor UPLOAD_PORT=/dev/cu.usbmodem...
make clean
```

`make` defaults to build. Defaults retain `PartitionScheme=min_spiffs`,
`CDCOnBoot=cdc`, upload speed 921600 and the prior compilation flags.
Setup pins ESP32 core 3.3.10 and NimBLE-Arduino 2.3.8, matching the installed
toolchain when this Makefile was created; the field device's toolchain is unknown.
No setup/install or flash occurs during a normal build.

The firmware remains unchanged. `lib/BleOta` and `scripts/ble_ota_upload.py`
are unchanged local copies from the former parent framework, so builds and OTA
uploads no longer depend on that framework or `board_config.mk`. The Makefile
explicitly selects the local BleOta library over globally installed copies.
Historical firmware remains in Git history.

USB uploads and serial monitoring require `UPLOAD_PORT`. OTA requires the
intended `BLE_DEVICE_ADDRESS` (a UUID on macOS) or an explicit
`BLE_DEVICE_NAME`; an address takes precedence. The device's name is stored
in NVS and defaults to `GalvoCtrl`. A name passed to make only selects the
upload target—it does not rename firmware. BLE OTA also requires Python `bleak`
(see below). Uploading still requires a device already running the OTA service.
Use `make help` for overrides. Build output stays in ignored `build/`.
No device was flashed during the migration.

## Python

The clients are standalone scripts; there is no local Python package.
Install `bleak` for BLE control, then run from the project root:

```sh
python3 -m pip install bleak
python3 galvo_client.py --help
python3 retrometer/retrometer.py                  # display only; no BLE needed
python3 retrometer/retrometer.py 4-13-2026         # historical date
python3 retrometer/retrometer.py --name Retrometer --watch 3600
python3 retrometer/retrometer.py --id <device-address> --channel 2
```

`galvo_client.py` retains the checked-in direct control and Claude usage polling.
Retrometer uses Bleak directly for optional BLE output. Its station data,
shadow approximation and gauge calculations are unchanged.

## Website

```sh
cd retrometer/web
npm ci
npm run dev
npm run check
npm run deploy
```

Local development serves on localhost. `npm run check` validates the deployment
bundle without publishing. `npm run deploy` publishes to the existing
`retrometer` Worker in your authenticated Cloudflare account. Wrangler must be logged
in with access to that account (`npx wrangler whoami`).

The scaffold uses Workers custom domains for `retrometer.online` and
`www.retrometer.online` and disables
workers.dev, matching Ringbeacon. The compatibility date is `2026-09-20`, matching Ringbeacon; observability stays
enabled. No account ID is hardcoded in the configuration. Cloudflare manages the custom domain DNS. The website is static HTML/CSS/JavaScript; only `public/`
is uploaded. Unknown navigation paths fall back to the page. There are no
server bindings, secrets, or frontend build step. Edit `retrometer/web/public/index.html`,
which replaces the old copy/paste dashboard source. Browser calibration stays in localStorage
on the production origin; localhost uses a separate calibration store.

For Cloudflare Git builds, use `retrometer/web` as the root directory, `npm ci && npm run check`
as the build command, and `npm run deploy` as the deploy command. Connecting Git
builds is separate from this local scaffold.



## Hardware Requirements

- **ESP32-C3 SuperMini** (or any ESP32-C3 board with USB-C)
- **Analog galvanometer**
- **Potentiometer** (recommended: multi-turn 20-100k ohm potentiometer)
- USB cable for programming and serial monitoring

### Wiring

Each galvo channel uses one GPIO pin. The default pin assignments are:

| Channel | GPIO |
|---------|------|
| 0       | 4    |
| 1       | 3    |
| 2       | 2    |
| 3       | 1    |
| 4       | 0    |
| 5       | 10   |

Wire each channel the same way:

```
GPIOx --> potentiometer (adjust to the high end of its resistance before calibration) --> galvo (+) --> galvo (-) --> GND
```

The potentiometer limits the maximum current through the galvanometer so that it is well within the limits of the current that can be drawn through each GPIO pin. Adjust it to set the full-scale deflection for a duty value of 1.0. You only need to wire up the channels you intend to use.

> **Note:** The ESP32-C3 GPIO can source up to ~40 mA at 3.3V. Most panel-mount galvanometers draw well under this. The potentiometer provides an adjustable safety margin.

> **Tip:** To change pin assignments or reduce the number of channels, edit the `GALVO_PINS[]` array in the sketch. The firmware automatically detects the number of active channels from the array length.  There is no penalty to leaving all defaults defined, even if you are planning on connecting fewer galvanometers.


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

The characteristic accepts two write formats:

**4-byte write** (backward compatible — targets channel 0):

| Bytes 0-3             | Description          |
|-----------------------|----------------------|
| float32 LE            | Value 0.0 - 1.0      |

**5-byte write** (multi-channel — targets a specific channel):

| Bytes 0-3             | Byte 4     | Description                  |
|-----------------------|------------|------------------------------|
| float32 LE            | uint8      | Value 0.0 - 1.0 + channel   |

- Values are **clamped** to [0.0, 1.0] on the device
- `NaN` and negative values are treated as 0.0
- Invalid channel numbers are rejected with a debug message
- Writes with length other than 4 or 5 bytes are silently ignored

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
python galvo_client.py 0.75             # write to channel 0 (default)
python galvo_client.py 0.75 --channel 2 # write to channel 2
python galvo_client.py 3:0.75           # shorthand: channel 3, value 0.75
```

### Interactive Mode

Run without arguments to enter interactive mode. The BLE connection stays open between writes:

```bash
python galvo_client.py
```

```
Enter values 0.0-1.0 or ch:value for a specific channel (q to quit):
> 0.5
Wrote 0.5000
> 2:0.75
Wrote 0.7500 to channel 2
> 0:0.0
Wrote 0.0000 to channel 0
> q
Disconnected.
```

Use `--channel` to set a default channel for all writes in a session:

```bash
python galvo_client.py --channel 3    # all writes target channel 3
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
python galvo_client.py --claudewatch 30              # channel 0
python galvo_client.py --claudewatch 30 --channel 2  # channel 2
```

This polls the Anthropic usage API every 30 seconds (or whatever interval you specify), inverts the percentage (so the gauge shows *remaining* capacity rather than used), and writes it to the galvo over the persistent BLE connection. A colored progress bar is printed to the terminal on each update.

Credentials are found automatically across platforms:

| Platform    | Location                                      |
|-------------|-----------------------------------------------|
| Linux / WSL | `~/.claude/.credentials.json`                 |
| macOS       | Keychain, then `~/.claude/.credentials.json`  |
| Windows     | Credential Manager, then `~/.claude/.credentials.json` |

### macOS Bluetooth Permissions

On macOS, your terminal application (Terminal, iTerm2, etc.) needs Bluetooth access. If the script fails to find the device:

1. Open **System Settings > Privacy & Security > Bluetooth**
2. Enable Bluetooth access for your terminal app
3. You may need to restart the terminal after granting permission


### Persistent device names

The default is `GalvoCtrl`; the existing working firmware also supports names
stored in NVS. The name characteristic is
`a1b2c3d4-5e6f-7890-abcd-ef1234567891` (read/write). Writing 1–20 UTF-8 bytes
persists the name and reboots the board. The original checked-in firmware lacks
this additional characteristic; Retrometer already tolerates its absence.
The retained CLI does not expose renaming. Firmware name support is unchanged.

## Consolidation and firmware compatibility

The Git baseline is `f3f8420` from `/Users/josh/Sync/arduino/esp32c3_galvo`, with
history and the `joshu017/galvable` remote retained. The original folders remain
intact as recovery copies. No device was flashed during consolidation.
The checked-in client is retained unchanged. The experimental Python package
and browser bridge were removed; Retrometer now uses Bleak directly. Artwork
and gauge calculations are unchanged. The extra sketches/retrometer folder contained
only the reference ephemeris, now in `retrometer/reference/`.

The three firmware baselines were compared during consolidation:

| Comparison | Existing differences |
|---|---|
| Committed → older working copy | Persistent name in NVS, additional name read/write characteristic, rename-triggered reboot, and boot/name logging. |
| Older working copy → destination | BleOta include, initialization before advertising, scan response enabled, OTA handling in loop, and shorter OTA-aware delay. |
| Destination → consolidated project | No firmware source changes. |

Across all three, the complete galvo write callback, duty-output function and
connect/disconnect callbacks are identical. Control UUIDs, 4-byte float and
5-byte float-plus-channel formats, clamping, channel pins, and 5 kHz/10-bit PWM
are unchanged. Historical firmware remains in Git and the original working
folder. Additive BLE services/advertising and loop changes existed before
this consolidation; source inspection does not prove which build is on the
field device or prove OTA/GATT behavior on hardware. Do not update that device
until its running firmware and a bench-tested replacement are identified.

The website source matched the production page apart from a leading newline.
The dashboard Worker had no bindings and used the wildcard route
`*retrometer.online/*`. The new scaffold serves the same HTML as static assets.
The old embedded `worker.txt` remains in the recovery copy, not as another active
source in this repository.

Validation completed: deployment dry run, local HTTP response identical to the
HTML source, live-page comparison, JavaScript syntax, Python syntax, Retrometer
CLI display/date smoke check, mocked BLE name/address selection and 4/5-byte
write checks, and the firmware source comparisons above.
The local ESP32-C3 Makefile build passed with core 3.3.10 and NimBLE 2.3.8.
Missing-target checks passed for USB upload, serial monitoring and BLE OTA.
Firmware source was not edited and no hardware connection was made. See the deployment status below for production cutover progress.

### Deployment status

Both hostnames verified on 2026-09-20 after deployment
`eed0b008-0e52-4a1a-a38d-2a8f464250b5`.
`retrometer.online` and `www.retrometer.online` are attached as Worker custom
domains. The old `www` CNAME was removed before attaching that hostname; a
CNAME alone does not give a hostname its own Worker binding. Both URLs serve
the same page. Browser calibration remains separate per origin.
The user removed the conflicting apex A record; after successful attachment,
the obsolete `*retrometer.online/*` route was removed. Cloudflare reports no
remaining zone routes. HTTPS returned 200 with HTML matching the canonical
source both before and after route removal. The scaffold has no hardcoded
account ID and disables workers.dev, matching RingBeacon.

## License

Apache License 2.0; see [LICENSE](LICENSE).
