#!/usr/bin/env python3
"""BLE OTA firmware upload tool for ESP32.

Sends a compiled .bin firmware file to an ESP32 running the BleOta library
over Bluetooth Low Energy.

Requires: pip install bleak
"""

import argparse
import asyncio
import os
import struct
import sys

from bleak import BleakClient, BleakScanner

SERVICE_UUID = "0000ff10-0000-1000-8000-00805f9b34fb"
CONTROL_UUID = "0000ff11-0000-1000-8000-00805f9b34fb"
DATA_UUID    = "0000ff12-0000-1000-8000-00805f9b34fb"

CMD_START = 0x01
CMD_END   = 0x02
CMD_ACK   = 0x03
CMD_NACK  = 0x04

CHUNK_SIZE = 512


async def find_device(name=None, address=None, timeout=5):
    """Scan for the target BLE device by name or address."""
    if address:
        print(f"Looking for device at {address}...")
        device = await BleakScanner.find_device_by_address(address, timeout=timeout)
        if device:
            print(f"Found: {device.name} ({device.address})")
            return device
        print("Device not found at that address")
        sys.exit(1)

    # Scan for OTA devices and match by advertised name (not cached name)
    print(f"Scanning for '{name}'..." if name else "Scanning for OTA devices...")
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)

    match = None
    ota_devices = []
    for dev, adv in sorted(devices.values(), key=lambda d: d[1].rssi, reverse=True):
        service_uuids = [u.lower() for u in (adv.service_uuids or [])]
        if SERVICE_UUID not in service_uuids:
            continue
        adv_name = adv.local_name or dev.name or "(unknown)"
        ota_devices.append((dev, adv_name))
        if name and adv_name == name and not match:
            match = dev

    if match:
        print(f"Found: {name} ({match.address})")
        return match

    # No match — show what's available
    print(f"'{name}' not found. Nearby OTA devices:" if name else "No target specified. Nearby OTA devices:")
    for dev, adv_name in ota_devices:
        print(f"  {adv_name:<24} {dev.address}")
    if not ota_devices:
        print("  (none found)")
    print("\nSet BLE_DEVICE_NAME or BLE_DEVICE_ADDRESS in board_config.mk to match.")
    sys.exit(1)


async def upload_firmware(firmware_path, name=None, address=None):
    """Upload firmware binary via BLE OTA."""
    if not os.path.exists(firmware_path):
        print(f"Firmware not found: {firmware_path}")
        sys.exit(1)

    with open(firmware_path, "rb") as f:
        firmware = f.read()
    firmware_size = len(firmware)
    print(f"Firmware: {firmware_path} ({firmware_size} bytes)")

    device = await find_device(name=name, address=address)

    ack_event = asyncio.Event()
    ack_status = [None]

    def on_notify(_sender, data):
        if len(data) >= 1:
            ack_status[0] = data[0]
            ack_event.set()

    async with BleakClient(device, timeout=30) as client:
        print("Connected")

        # Verify OTA service is visible (macOS caches stale GATT tables)
        ota_svc = client.services.get_service(SERVICE_UUID)
        if not ota_svc:
            print("Error: OTA service not found in GATT table.")
            print("macOS caches BLE services — toggle Bluetooth off/on in")
            print("System Settings, then retry.")
            return False

        await client.start_notify(CONTROL_UUID, on_notify)

        # Send START with 4-byte little-endian firmware size
        start_cmd = struct.pack("<BI", CMD_START, firmware_size)
        ack_event.clear()
        await client.write_gatt_char(CONTROL_UUID, start_cmd)

        try:
            await asyncio.wait_for(ack_event.wait(), timeout=5)
        except asyncio.TimeoutError:
            print("Timeout waiting for START acknowledgment")
            return False

        if ack_status[0] != CMD_ACK:
            print("Device rejected OTA start")
            return False

        # Derive chunk size from negotiated MTU (ATT header = 3 bytes)
        chunk_size = max(client.mtu_size - 3, 20)
        print(f"Uploading (MTU {client.mtu_size}, {chunk_size}B chunks)...")

        # Send firmware in chunks (write-without-response for speed)
        offset = 0
        while offset < firmware_size:
            chunk = firmware[offset : offset + chunk_size]
            await client.write_gatt_char(DATA_UUID, chunk, response=False)
            offset += len(chunk)
            pct = (offset * 100) // firmware_size
            bar = "#" * (pct // 5) + "-" * (20 - pct // 5)
            print(f"\r  [{bar}] {pct:3d}%  ({offset}/{firmware_size})", end="", flush=True)
            await asyncio.sleep(0.02)

        print("\nFinalizing...")

        # Send END — the device may reboot before this write returns,
        # so a BleakError disconnect here counts as success.
        end_cmd = struct.pack("<B", CMD_END)
        ack_event.clear()
        try:
            await client.write_gatt_char(CONTROL_UUID, end_cmd)
        except Exception:
            # Device rebooted mid-write
            print("OTA successful — device rebooted.")
            return True

        try:
            await asyncio.wait_for(ack_event.wait(), timeout=10)
            if ack_status[0] == CMD_ACK:
                print("OTA successful — device is rebooting.")
                return True
            else:
                print("OTA finalization failed")
                return False
        except asyncio.TimeoutError:
            # Device likely rebooted before the ACK could be sent
            print("Device rebooted. OTA assumed successful.")
            return True


def main():
    parser = argparse.ArgumentParser(description="BLE OTA firmware upload for ESP32")
    parser.add_argument("--firmware", "-f", required=True, help="Path to .bin firmware file")
    parser.add_argument("--name", "-n", help="BLE device name to scan for")
    parser.add_argument("--address", "-a", help="BLE device address (e.g. AA:BB:CC:DD:EE:FF)")
    args = parser.parse_args()

    if not args.name and not args.address:
        parser.error("provide --name or --address")

    success = asyncio.run(upload_firmware(args.firmware, name=args.name, address=args.address))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
