# Galvable contributor instructions

## Scope and layout

README.md is the user, hardware, protocol, setup and migration reference.
Keep shared project documentation in README.md and agent instructions in this
file. retrometer/README.md is a lightweight application-specific quick start;
do not duplicate the shared wiring, firmware or deployment guide there.
Do not create parallel guides, plans or copy/paste Worker sources.

This project targets ESP32-C3 only. Its local Makefile replaces the parent
framework build rules and board_config.mk. Keep the existing partition/USB
settings and compilation flags. lib/BleOta and scripts/ble_ota_upload.py are
unchanged copies of the former framework OTA implementation; preserve OTA.
Do not reintroduce parent-path dependencies or auto-detected board settings.
`galvable/galvable.ino` is the active sketch; keep the directory and sketch
basename identical. The firmware name comes from NVS with a
GalvoCtrl default. An installed device is in the field: firmware source and
wire behavior must remain stable unless a firmware change is explicitly requested.

`galvo_client.py` is the unchanged checked-in client. Retrometer is a standalone
script at retrometer/retrometer.py using Bleak directly for optional BLE output.
Do not recreate the experimental Python package or browser bridge. The inner
`galvable/` folder is firmware only. `retrometer/` also contains the website,
faceplate artwork and reference ephemeris.

## Compatibility contract

Preserve the service/control UUIDs, little-endian float write format (4 bytes
for channel zero, 5 bytes for float plus channel), clamp behavior, channel
pins {4,3,2,1,0,10}, 5 kHz/10-bit PWM and duty scaling 0–1000.
Persistent names, their characteristic and automatic rename reboot already
exist in working firmware; older committed firmware does not have them.
Do not assume the field device runs the newest local source. Additive GATT
services and advertising changes need bench validation before firmware rollout.
README.md records the firmware comparison; original versions remain in Git
and the preserved source folder.
No firmware upload is implied by a build, website deployment or cleanup request.

## Website and validation

retrometer/web/public/index.html is the sole web source. retrometer/web/wrangler.jsonc and the locked
npm dependencies configure an assets-only Worker named retrometer. Follow
RingBeacon's web layout and npm dev/build/check/deploy commands. Use the
retrometer.online and www.retrometer.online custom domains, workers_dev false,
and no hardcoded account_id. A DNS CNAME alone does not bind www to the Worker.
Confirm the logged-in Cloudflare account before deployment. Use Context7 for
current Workers/Wrangler documentation and check the installed config schema.
Keep the lockfile unless a dependency update is needed. Never publish Python,
firmware or artwork as web assets.

Run npm ci and npm run check in retrometer/web/ for a clean deployment dry run. Verify
local serving and relevant browser behavior for web changes. Preserve the
production origin and calibration storage keys. Python checks should exercise
direct script execution and BLE packet compatibility. For firmware changes, use
make build from the project root and compare the protocol
against all recorded baselines; compilation is not hardware validation.
Keep README commands and behavior in sync. Do not commit credentials, local
board settings, .venv, node_modules, .wrangler, caches or build outputs.
USB flash/monitor require an explicit UPLOAD_PORT; BLE OTA requires an explicit
BLE_DEVICE_ADDRESS or BLE_DEVICE_NAME. Never flash as part of build validation.
Preserve the license and Git history. Original source folders are recovery
copies, not additional active development locations.
