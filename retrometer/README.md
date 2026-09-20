# Retrometer

A Mercury retrograde tracker displayed on a Galvable-driven analog meter.
The needle moves through direct, shadow, and retrograde phases using bundled
station dates; shadow periods are approximations.

Open [retrometer.online](https://retrometer.online) in a browser with Web Bluetooth
support to connect a meter and calibrate its shadow/retrograde marks. Calibration
is saved per device in that browser.

For the Python version, run from this folder:

```sh
python3 retrometer.py                              # display only
python3 retrometer.py 4-13-2026                     # check a date
python3 retrometer.py --name Retrometer --watch 3600 # update a meter hourly
```

BLE output requires `bleak`. Use `--id <device-address>` instead of `--name`
to select by address, and `--channel 2` to target another output (default: 0).

`web/` holds the website (`npm ci`, then `npm run dev` from that folder).
The SVGs are printable faceplates; `reference/` contains the source ephemeris.
See the [project README](../README.md) for wiring, firmware and deployment.
