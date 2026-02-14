#!/usr/bin/env python3
"""BLE client for GalvoCtrl ESP32-C3 galvanometer controller."""

import asyncio
import json
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from bleak import BleakScanner, BleakClient

DEVICE_NAME = "GalvoCtrl"
SERVICE_UUID = "e0f3a8b1-4c6d-4e9f-8b2a-7d1c5f3e9a0b"
CHARACTERISTIC_UUID = "a1b2c3d4-5e6f-7890-abcd-ef1234567890"

# Claude Code OAuth constants
USAGE_API = "https://api.anthropic.com/api/oauth/usage"
TOKEN_REFRESH_API = "https://console.anthropic.com/api/oauth/token"
CLAUDE_CODE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
USER_AGENT = "claude-code/2.1.1"


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


async def write_value(client, value, channel=None):
    """Write a float value to the galvo, optionally targeting a specific channel.

    4-byte write (float only) → device defaults to channel 0.
    5-byte write (float + channel byte) → targets a specific channel.
    """
    if channel is not None:
        data = struct.pack("<fB", value, channel)
        await client.write_gatt_char(CHARACTERISTIC_UUID, data)
        print(f"Wrote {value:.4f} to channel {channel}")
    else:
        data = struct.pack("<f", value)
        await client.write_gatt_char(CHARACTERISTIC_UUID, data)
        print(f"Wrote {value:.4f}")


# ── Claude Code usage helpers ────────────────────────────────────────────────

def _load_creds_from_file(filepath):
    """Load credentials from a JSON file."""
    try:
        return json.loads(filepath.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _load_creds_from_keychain():
    """Load credentials from macOS Keychain."""
    if sys.platform != "darwin":
        return None
    try:
        raw = subprocess.check_output(
            ["security", "find-generic-password", "-s",
             "Claude Code-credentials", "-w"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        return json.loads(raw)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def _load_creds_from_wincred():
    """Load credentials from Windows Credential Manager via PowerShell."""
    if sys.platform != "win32":
        return None
    # Use the PasswordVault WinRT API through PowerShell — no extra deps
    ps_script = (
        '[Windows.Security.Credentials.PasswordVault,Windows.Security.Credentials,ContentType=WindowsRuntime] | Out-Null; '
        '$v = New-Object Windows.Security.Credentials.PasswordVault; '
        '$c = $v.Retrieve("Claude Code-credentials", "credentials"); '
        '$c.RetrievePassword(); '
        '$c.Password'
    )
    try:
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        return json.loads(raw)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        pass

    # Fallback: try cmdkey-based approach for generic credentials
    try:
        # cmdkey can't retrieve passwords, but the file path fallback
        # covers most Windows cases since WSL uses file-based creds
        return None
    except Exception:
        return None


def _load_credentials():
    """Find and return Claude Code OAuth credentials.

    Search order:
      1. File: ~/.claude/.credentials.json  (Linux, WSL, sometimes Windows)
      2. File: ~/.claude/credentials.json    (alternative)
      3. macOS Keychain                      (macOS)
      4. Windows Credential Manager          (Windows)
    """
    home = Path.home()
    paths = [
        home / ".claude" / ".credentials.json",
        home / ".claude" / "credentials.json",
    ]
    for p in paths:
        creds = _load_creds_from_file(p)
        if creds and creds.get("claudeAiOauth", {}).get("accessToken"):
            return creds, str(p)

    # Platform-specific credential stores
    creds = _load_creds_from_keychain()
    if creds and creds.get("claudeAiOauth", {}).get("accessToken"):
        return creds, "macOS Keychain"

    creds = _load_creds_from_wincred()
    if creds and creds.get("claudeAiOauth", {}).get("accessToken"):
        return creds, "Windows Credential Manager"

    checked = [str(p) for p in paths]
    if sys.platform == "darwin":
        checked.append('macOS Keychain ("Claude Code-credentials")')
    elif sys.platform == "win32":
        checked.append('Windows Credential Manager ("Claude Code-credentials")')

    print("Could not find Claude Code credentials.")
    print("Checked:")
    for loc in checked:
        print(f"  - {loc}")
    print("\nMake sure you've logged into Claude Code at least once.")
    sys.exit(1)


def _refresh_token(refresh_token):
    """Exchange a refresh token for a new access token."""
    payload = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLAUDE_CODE_CLIENT_ID,
    }).encode()
    req = Request(TOKEN_REFRESH_API, data=payload,
                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("access_token")
    except (URLError, HTTPError):
        return None


def _fetch_usage(access_token):
    """Call the Anthropic usage API. Returns (data_dict, needs_refresh)."""
    req = Request(USAGE_API, headers={
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {access_token}",
        "anthropic-beta": "oauth-2025-04-20",
    })
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()), False
    except HTTPError as e:
        if e.code == 401:
            return None, True
        raise


def get_claude_usage_pct():
    """Return the 5-hour utilization percentage, handling token refresh."""
    creds, source = _load_credentials()
    oauth = creds["claudeAiOauth"]
    access_token = oauth["accessToken"]

    data, needs_refresh = _fetch_usage(access_token)

    if needs_refresh and oauth.get("refreshToken"):
        print("  Token expired, refreshing...", end=" ", flush=True)
        new_token = _refresh_token(oauth["refreshToken"])
        if new_token:
            print("done.")
            data, _ = _fetch_usage(new_token)
        else:
            print("failed.")
            return None

    if not data:
        return None

    return data.get("five_hour", {}).get("utilization")


def _format_reset(iso_str):
    """Format a reset timestamp as a human-readable relative string."""
    if not iso_str:
        return "N/A"
    reset = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    diff = reset - now
    secs = diff.total_seconds()
    if secs <= 0:
        return "already reset"
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    local = reset.astimezone().strftime("%-I:%M %p")
    if h > 24:
        d = h // 24
        return f"{d}d {h % 24}h ({local})"
    return f"{h}h {m}m ({local})"


# ── Claude watch mode ────────────────────────────────────────────────────────

async def claude_watch(client, interval, channel=None):
    """Continuously poll Claude usage and update the galvanometer."""
    ch_label = f" (ch {channel})" if channel is not None else ""
    print(f"\n  Claude Code gauge{ch_label} — polling every {interval}s (Ctrl+C to stop)\n")

    while True:
        pct = get_claude_usage_pct()
        if pct is not None:
            remaining = (100.0 - pct) / 100.0
            remaining = max(0.0, min(1.0, remaining))
            if channel is not None:
                data = struct.pack("<fB", remaining, channel)
            else:
                data = struct.pack("<f", remaining)
            await client.write_gatt_char(CHARACTERISTIC_UUID, data)

            ts = datetime.now().strftime("%H:%M:%S")
            bar_width = 30
            filled = round(pct / 100 * bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)

            # Color: green < 70, yellow 70-90, red >= 90
            if pct >= 90:
                color, reset = "\033[31m", "\033[0m"
            elif pct >= 70:
                color, reset = "\033[33m", "\033[0m"
            else:
                color, reset = "\033[32m", "\033[0m"

            print(f"  [{ts}]  {color}{bar}{reset} {pct:.1f}% used → galvo {remaining:.4f}")
        else:
            print(f"  [{datetime.now().strftime('%H:%M:%S')}]  ⚠ Could not fetch usage")

        await asyncio.sleep(interval)


# ── Main ─────────────────────────────────────────────────────────────────────

def _parse_channel_value(s):
    """Parse 'ch:value' or plain 'value' string. Returns (value, channel)."""
    if ":" in s:
        parts = s.split(":", 1)
        ch = int(parts[0])
        val = float(parts[1])
        return val, ch
    return float(s), None


async def main():
    args = sys.argv[1:]

    debug = "--debug" in args
    if debug:
        args.remove("--debug")

    # Check for --channel <n>
    channel = None
    if "--channel" in args:
        idx = args.index("--channel")
        if idx + 1 >= len(args):
            print("--channel requires a channel number (0-5)")
            sys.exit(1)
        try:
            channel = int(args[idx + 1])
            if channel < 0:
                raise ValueError
        except ValueError:
            print(f"Invalid --channel value: {args[idx + 1]}")
            sys.exit(1)
        args = args[:idx] + args[idx + 2:]

    # Check for --claudewatch <seconds>
    claude_watch_interval = None
    if "--claudewatch" in args:
        idx = args.index("--claudewatch")
        if idx + 1 >= len(args):
            print("--claudewatch requires an interval in seconds")
            sys.exit(1)
        try:
            claude_watch_interval = int(args[idx + 1])
            if claude_watch_interval <= 0:
                raise ValueError
        except ValueError:
            print(f"Invalid --claudewatch interval: {args[idx + 1]}")
            sys.exit(1)
        args = args[:idx] + args[idx + 2:]

    device = await find_device(debug=debug)
    if not device:
        print("Device not found. Make sure ESP32-C3 is powered and advertising.")
        sys.exit(1)
    print(f"Found {DEVICE_NAME} at {device.address}")

    try:
        async with BleakClient(device) as client:
            if claude_watch_interval is not None:
                await claude_watch(client, claude_watch_interval, channel)
            elif args:
                value, ch_override = _parse_channel_value(args[0])
                ch = ch_override if ch_override is not None else channel
                if not (0.0 <= value <= 1.0):
                    print("Value must be between 0.0 and 1.0")
                    sys.exit(1)
                await write_value(client, value, ch)
            else:
                ch_hint = f" or ch:value for a specific channel" if channel is None else ""
                print(f"Enter values 0.0-1.0{ch_hint} (q to quit):")
                while True:
                    try:
                        raw = input("> ").strip()
                        if raw.lower() == "q":
                            break
                        val, ch_override = _parse_channel_value(raw)
                        ch = ch_override if ch_override is not None else channel
                        if not (0.0 <= val <= 1.0):
                            print("Value must be between 0.0 and 1.0")
                            continue
                        await write_value(client, val, ch)
                    except ValueError:
                        print("Invalid input (use 0.5 or 2:0.5)")
                    except KeyboardInterrupt:
                        break
    except KeyboardInterrupt:
        pass
    print("Disconnected.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDisconnected.")
