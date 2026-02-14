#!/usr/bin/env python3
"""BLE client for GalvoCtrl ESP32-C3 galvanometer controller."""

import asyncio
import struct
import sys

from bleak import BleakScanner, BleakClient

DEVICE_NAME = "GalvoCtrl"
SERVICE_UUID = "e0f3a8b1-4c6d-4e9f-8b2a-7d1c5f3e9a0b"
CHARACTERISTIC_UUID = "a1b2c3d4-5e6f-7890-abcd-ef1234567890"


def _is_galvo(d, adv):
    return adv.local_name == DEVICE_NAME or SERVICE_UUID in adv.service_uuids


async def find_device(debug=False, timeout=10.0):
    print(f"Scanning for {DEVICE_NAME}...")

    if debug:
        # Full scan to list all devices
        discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
        print(f"\n{'='*60}")
        print(f"Found {len(discovered)} BLE device(s):")
        print(f"{'='*60}")
        items = sorted(discovered.values(), key=lambda x: x[0].address)
        with_svcs = [(d, adv) for d, adv in items if adv.service_uuids]
        for d, adv in with_svcs:
            name = adv.local_name or "(no name)"
            svcs = ", ".join(adv.service_uuids)
            print(f"  {name:30s}  {d.address}")
            print(f"    advertised services: {svcs}")
        print(f"  ({len(discovered) - len(with_svcs)} other device(s) with no advertised services)")
        print(f"{'='*60}\n")
        for d, adv in discovered.values():
            if _is_galvo(d, adv):
                return d
        return None

    # Fast scan: return immediately when device is found
    found_event = asyncio.Event()
    result = [None]

    def on_detect(d, adv):
        if _is_galvo(d, adv):
            result[0] = d
            found_event.set()

    scanner = BleakScanner(detection_callback=on_detect)
    await scanner.start()
    try:
        await asyncio.wait_for(found_event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    await scanner.stop()
    return result[0]


async def write_value(client, value):
    data = struct.pack("<f", value)
    await client.write_gatt_char(CHARACTERISTIC_UUID, data)
    print(f"Wrote {value:.4f}")


async def main():
    debug = "--debug" in sys.argv
    if debug:
        sys.argv.remove("--debug")
    device = await find_device(debug=debug)
    if not device:
        print("Device not found. Make sure ESP32-C3 is powered and advertising.")
        sys.exit(1)
    print(f"Found {DEVICE_NAME} at {device.address}")

    try:
        async with BleakClient(device) as client:
            if len(sys.argv) > 1:
                value = float(sys.argv[1])
                if not (0.0 <= value <= 1.0):
                    print("Value must be between 0.0 and 1.0")
                    sys.exit(1)
                await write_value(client, value)
            else:
                print("Enter values 0.0-1.0 (q to quit):")
                while True:
                    try:
                        raw = input("> ").strip()
                        if raw.lower() == "q":
                            break
                        val = float(raw)
                        if not (0.0 <= val <= 1.0):
                            print("Value must be between 0.0 and 1.0")
                            continue
                        await write_value(client, val)
                    except ValueError:
                        print("Invalid number")
                    except KeyboardInterrupt:
                        break
    except KeyboardInterrupt:
        pass
    print("Disconnected.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
