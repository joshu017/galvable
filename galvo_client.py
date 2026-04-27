#!/usr/bin/env python3
"""BLE client for GalvoCtrl ESP32-C3 galvanometer controller."""

import asyncio
import json
import readline  # noqa: F401 — enables arrow-key history in input()
import struct
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import galvable

HELP_TEXT = """\
usage: galvo_client.py [options] [value]

BLE client for the GalvoCtrl ESP32-C3 galvanometer controller.

positional arguments:
  value                 float 0.0-1.0 to write (or ch:value, e.g. 2:0.75).
                        omit for interactive mode.

options:
  --name NAME           connect to a specific galvo by its device name
  --id ADDRESS          connect to a specific galvo by BLE address
  --channel N           target channel for all writes (0-5)
  --claudewatch         run a web bridge that accepts Claude Code usage
                        data from a browser bookmarklet and drives the
                        galvo accordingly
  --scan                scan for GalvoCtrl devices and report their IDs
  --rename ID NAME      rename a galvo (ID is its name or BLE address)
  --debug               verbose BLE scan listing all discovered devices
  --help                show this help message and exit
"""


# ── Claude watch mode (web bridge) ──────────────────────────────────────────

_OVERLAY_JS = """\
(function(){
  var B="http://localhost:__PORT__",P=15000;
  function scrape(){
    for(var p of document.querySelectorAll("p"))
      if(p.textContent.trim()==="Current session"){
        var c=p.closest(".flex.flex-row");if(!c)continue;
        var u=c.querySelector('p[class*="text-right"]');
        if(u){var m=u.textContent.match(/(\\d+)%/);if(m)return+m[1]}
      }
    return null}
  var h=document.createElement("div");
  Object.assign(h.style,{position:"fixed",bottom:"12px",right:"12px",zIndex:99999,
    background:"#1a1a2e",color:"#0f0",fontFamily:"monospace",fontSize:"13px",
    padding:"8px 12px",borderRadius:"8px",border:"1px solid #333",
    boxShadow:"0 2px 12px rgba(0,0,0,.5)"});
  h.innerHTML='<strong style="color:#0ff">GALVO</strong> <span id="gv">--</span>';
  document.body.appendChild(h);
  var gv=document.getElementById("gv");
  async function poll(){
    var pct=scrape();if(pct===null){gv.textContent="??";return}
    try{
      var r=await fetch(B+"/update",{method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({percent:pct})});
      if(r.ok){var d=await r.json();
        gv.textContent=pct+"% \\u2192 "+d.galvo.toFixed(2);
        gv.style.color="#0f0"}
      else{gv.textContent=pct+"% (err)";gv.style.color="#f00"}
    }catch(_){gv.textContent=pct+"% (offline)";gv.style.color="#f80"}
  }
  function refresh(){var b=document.querySelector('button[aria-label="Refresh usage limits"]');if(b)b.click()}
  poll();setInterval(function(){refresh();setTimeout(poll,2000)},P);
})();
"""


def _make_web_handler(loop, conn, channel, js_content):
    """Create an HTTP handler that bridges browser POST → BLE write."""

    class Handler(BaseHTTPRequestHandler):
        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            body = js_content.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length))
                pct = float(data.get("percent", 0))
                remaining = max(0.0, min(1.0, (100.0 - pct) / 100.0))

                ble_ok = False
                if conn:
                    if channel is not None:
                        payload = struct.pack("<fB", remaining, channel)
                    else:
                        payload = struct.pack("<f", remaining)
                    try:
                        fut = asyncio.run_coroutine_threadsafe(
                            conn.write_raw(payload), loop,
                        )
                        fut.result(timeout=5)
                        ble_ok = True
                    except Exception as e:
                        print(f"  \u26a0 BLE write failed: {e}")

                # Terminal bar
                bar_w = 30
                filled = round(pct / 100 * bar_w)
                bar = "\u2588" * filled + "\u2591" * (bar_w - filled)
                if pct >= 90:
                    c, r = "\033[31m", "\033[0m"
                elif pct >= 70:
                    c, r = "\033[33m", "\033[0m"
                else:
                    c, r = "\033[32m", "\033[0m"
                ble_s = f" \u2192 galvo {remaining:.4f}" if ble_ok else " (no BLE)"
                print(f"  {c}{bar}{r} {pct:.0f}% used{ble_s}")

                resp = json.dumps({
                    "ack": ble_ok, "pct": pct, "galvo": round(remaining, 4),
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._cors()
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                self.send_response(500)
                self._cors()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        def log_message(self, *_a):
            pass

    return Handler


async def claude_watch(conn, channel=None):
    """Serve the JS overlay and bridge browser scrape → BLE."""
    port = 8384
    js_content = _OVERLAY_JS.replace("__PORT__", str(port))

    loop = asyncio.get_running_loop()
    handler_cls = _make_web_handler(loop, conn, channel, js_content)
    httpd = HTTPServer(("127.0.0.1", port), handler_cls)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    ble_label = "" if conn else " (no BLE device)"
    ch_label = f" ch{channel}" if channel is not None else ""
    bm = (
        f"javascript:void(fetch('http://localhost:{port}/overlay.js')"
        ".then(r=>r.text()).then(t=>{{const s=document.createElement('script');"
        "s.nonce=document.querySelector('script[nonce]')?.nonce;"
        "s.textContent=t;document.head.appendChild(s)}}))"
    )

    print(f"\n  Claude watch{ch_label}{ble_label} on http://localhost:{port}")
    print(f"\n  Bookmark URL (add to Chrome bookmarks bar):")
    print(f"    {bm}")
    print(f"\n  Open claude.ai/settings/usage and click the bookmark.")
    print(f"  Ctrl+C to stop.\n")

    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        httpd.shutdown()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_channel_value(s):
    """Parse 'ch:value' or plain 'value' string. Returns (value, channel)."""
    if ":" in s:
        parts = s.split(":", 1)
        ch = int(parts[0])
        val = float(parts[1])
        return val, ch
    return float(s), None


async def do_scan():
    """Scan and print discovered galvos."""
    print("Scanning for GalvoCtrl devices (5s)...\n")
    devices = await galvable.scan()
    if not devices:
        print("No GalvoCtrl devices found.")
        return
    print(f"Found {len(devices)} GalvoCtrl device(s):\n")
    for d in devices:
        name = d.name or "(unknown)"
        rssi = d.rssi if d.rssi is not None else "?"
        print(f"  {name:20s}  {d.address}  RSSI {rssi}")


async def do_rename(identifier, new_name):
    """Rename a galvo by name or BLE address."""
    is_address = ":" in identifier or "-" in identifier
    kwargs = {"address": identifier} if is_address else {"name": identifier}

    print(f"Scanning for device '{identifier}'...")
    try:
        async with galvable.connect(**kwargs) as g:
            print(f"Found at {g.address}, current name: {g.name}")
            await g.rename(new_name)
            print(f"Renamed to '{new_name}' — device is rebooting.")
    except galvable.DeviceNotFoundError:
        print(f"Device '{identifier}' not found.")
        sys.exit(1)


# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        print(HELP_TEXT)
        sys.exit(0)

    if "--scan" in args:
        await do_scan()
        return

    if "--rename" in args:
        idx = args.index("--rename")
        if idx + 2 >= len(args):
            print("--rename requires two arguments: ID and NAME")
            print("  ID is the device's current name or BLE address")
            print("  e.g. --rename GalvoCtrl MyGalvo")
            print("  e.g. --rename AA:BB:CC:DD:EE:FF MyGalvo")
            sys.exit(1)
        await do_rename(args[idx + 1], args[idx + 2])
        return

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

    # Check for --name <device name>
    target_name = None
    if "--name" in args:
        idx = args.index("--name")
        if idx + 1 >= len(args):
            print("--name requires a device name")
            sys.exit(1)
        target_name = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    # Check for --id <BLE address>
    target_id = None
    if "--id" in args:
        idx = args.index("--id")
        if idx + 1 >= len(args):
            print("--id requires a BLE address")
            sys.exit(1)
        target_id = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    # Check for --claudewatch
    claude_watch_mode = "--claudewatch" in args
    if claude_watch_mode:
        args.remove("--claudewatch")

    # Connect
    try:
        async with galvable.connect(
            name=target_name, address=target_id
        ) as conn:
            print(f"Found {conn.name or 'GalvoCtrl'} at {conn.address}")

            if claude_watch_mode:
                await claude_watch(conn, channel)
            elif args:
                value, ch_override = _parse_channel_value(args[0])
                ch = ch_override if ch_override is not None else channel
                await conn.write(value, ch)
                ch_label = f" to channel {ch}" if ch is not None else ""
                print(f"Wrote {value:.4f}{ch_label}")
            else:
                ch_hint = " or ch:value for a specific channel" if channel is None else ""
                print(f"Enter values 0.0-1.0{ch_hint} (q to quit):")
                while True:
                    try:
                        raw = input("> ").strip()
                        if raw.lower() == "q":
                            break
                        val, ch_override = _parse_channel_value(raw)
                        ch = ch_override if ch_override is not None else channel
                        await conn.write(val, ch)
                        ch_label = f" to channel {ch}" if ch is not None else ""
                        print(f"Wrote {val:.4f}{ch_label}")
                    except ValueError as e:
                        print(f"Invalid input: {e}")
                    except KeyboardInterrupt:
                        break
    except galvable.DeviceNotFoundError:
        if claude_watch_mode:
            print("BLE device not found — running in display-only mode.")
            try:
                await claude_watch(None, channel)
            except KeyboardInterrupt:
                pass
            return
        print("Device not found. Make sure ESP32-C3 is powered and advertising.")
        sys.exit(1)
    except KeyboardInterrupt:
        pass
    print("Disconnected.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDisconnected.")
