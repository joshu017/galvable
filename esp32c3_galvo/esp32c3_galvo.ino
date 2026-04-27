/*
 * Galvable — BLE Multi-Channel Galvanometer Controller
 *
 * Firmware for ESP32-C3 that exposes up to 6 independent PWM channels
 * over a single BLE characteristic. Each channel drives an analog
 * galvanometer via 10-bit PWM at 5 kHz.
 *
 * BLE Write Protocol:
 *   - 4-byte write: IEEE 754 little-endian float (0.0–1.0) → channel 0
 *   - 5-byte write: same float + 1-byte channel index (0–5)
 *
 * The 4-byte mode exists for backward compatibility and simplicity —
 * if you only have one galvo, you never need to think about channels.
 *
 * A separate NAME_CHARACTERISTIC allows renaming the device over BLE.
 * The name is stored in NVS (non-volatile storage) and persists across
 * reboots. Write a UTF-8 string (max 20 bytes) to rename; read to get
 * the current name.
 *
 * Dependencies:
 *   - NimBLE-Arduino v2.x (h2zero) — lightweight BLE stack
 *   - ESP32 Arduino core v3.x (Espressif)
 *
 * Hardware: ESP32-C3 SuperMini (or any ESP32-C3 dev board)
 * License: Apache 2.0
 */

#include <NimBLEDevice.h>
#include <Preferences.h>

// WORKAROUND: Arduino ESP32 core 3.x releases BT controller memory before
// setup() runs unless a library explicitly registers BT usage. NimBLE-Arduino
// 2.x doesn't do this, so including this header prevents a Guru Meditation
// crash (instruction access fault at 0x00000000) during NimBLEDevice::init().
// See: https://github.com/espressif/arduino-esp32/issues/4243
#include "esp32-hal-bt-mem.h"


// ── Pin Assignments ─────────────────────────────────────────────────────────

// Built-in LED on the ESP32-C3 SuperMini board. Active LOW: writing LOW
// turns it on, HIGH turns it off. Used as a BLE connection indicator.
#define LED_PIN 8

// PWM output pins — one per galvo channel. The array length determines
// how many channels the firmware will initialize. To use fewer channels,
// simply shorten this array. Unused channels have zero overhead since
// setup() only initializes what's defined here.
static const uint8_t GALVO_PINS[] = {4, 3, 2, 1, 0, 10};


// ── Debug Configuration ─────────────────────────────────────────────────────

// Uncomment to enable verbose serial output with flush-after-print
// (ensures debug messages are visible even if the device crashes shortly
// after printing) and a 2-second boot delay to give the serial monitor
// time to connect.
// #define DEBUG

#ifdef DEBUG
  // Flush after every print so output is captured before any crash
  #define dbg(fmt, ...) do { Serial.printf(fmt, ##__VA_ARGS__); Serial.flush(); } while(0)
#else
  // In release mode, still print but don't flush (better throughput)
  #define dbg(fmt, ...) Serial.printf(fmt, ##__VA_ARGS__)
#endif


// ── BLE Configuration ───────────────────────────────────────────────────────

// Default device name, used when no custom name has been saved to NVS.
#define DEFAULT_DEVICE_NAME "GalvoCtrl"

// Maximum length for a custom device name (BLE advertisement space is tight).
#define MAX_NAME_LEN 20

// Custom service and characteristic UUIDs. The galvo characteristic handles
// all PWM channels. The name characteristic allows remote renaming.
#define SERVICE_UUID             "e0f3a8b1-4c6d-4e9f-8b2a-7d1c5f3e9a0b"
#define CHARACTERISTIC_UUID      "a1b2c3d4-5e6f-7890-abcd-ef1234567890"
#define NAME_CHARACTERISTIC_UUID "a1b2c3d4-5e6f-7890-abcd-ef1234567891"


// ── Derived Constants & State ───────────────────────────────────────────────

// Number of active galvo channels, auto-calculated from GALVO_PINS array.
static const uint8_t NUM_CHANNELS = sizeof(GALVO_PINS) / sizeof(GALVO_PINS[0]);

// Current duty cycle for each channel (0–1000 out of 1023 max).
// Stored so it could be read back or used for status reporting.
int duty[sizeof(GALVO_PINS) / sizeof(GALVO_PINS[0])];

// NVS storage for persistent device name
Preferences prefs;

// Active device name (loaded from NVS at boot)
char deviceName[MAX_NAME_LEN + 1];


// ── PWM Output ──────────────────────────────────────────────────────────────

/**
 * Set the PWM duty cycle for a specific galvo channel.
 *
 * @param ch  Channel index (0 to NUM_CHANNELS-1)
 * @param f   Float value 0.0–1.0 (should already be clamped by caller)
 *
 * The float is scaled to a duty cycle of 0–1000 (out of a 10-bit max of
 * 1023). We intentionally cap at 1000 rather than 1023 to leave a small
 * margin at the top of the PWM range.
 */
void set_duty(uint8_t ch, float f) {
    if (ch >= NUM_CHANNELS) {
        dbg("Invalid channel %d (max %d)\n", ch, NUM_CHANNELS - 1);
        return;
    }
    duty[ch] = (int)(f * 1000.0f);
    ledcWrite(GALVO_PINS[ch], duty[ch]);
    dbg("Ch %d: %.4f -> duty %d\n", ch, f, duty[ch]);
}


// ── BLE Server Callbacks ────────────────────────────────────────────────────

/**
 * Handles BLE connection and disconnection events.
 *
 * On connect:    LED turns on to indicate an active client.
 * On disconnect: LED turns off, and advertising restarts so the device
 *                is discoverable again without requiring a reboot.
 */
class ServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo) override {
        dbg("Client connected\n");
        digitalWrite(LED_PIN, LOW);   // LED on (active low)
    }
    void onDisconnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo, int reason) override {
        dbg("Client disconnected (reason=%d) - restarting advertising\n", reason);
        digitalWrite(LED_PIN, HIGH);  // LED off
        NimBLEDevice::startAdvertising();  // Allow new connections
    }
};


// ── BLE Characteristic Callbacks ────────────────────────────────────────────

/**
 * Handles writes to the galvo characteristic.
 *
 * Two payload formats are supported:
 *
 *   4 bytes: [float32 LE]           → writes to channel 0 (backward compat)
 *   5 bytes: [float32 LE] [uint8]   → writes to the specified channel
 *
 * The float-first layout means a plain 4-byte float write "just works"
 * for single-channel use, and the optional 5th byte extends it to
 * multi-channel without breaking the original protocol.
 *
 * Values are clamped to [0.0, 1.0]. NaN and negative values become 0.0.
 * Any other payload length is silently ignored.
 */
class GalvoCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* pCharacteristic, NimBLEConnInfo& connInfo) override {
        NimBLEAttValue val = pCharacteristic->getValue();
        float f;
        uint8_t ch = 0;  // Default to channel 0

        if (val.size() == 4) {
            // 4-byte write: float only → channel 0 (backward compatible)
            memcpy(&f, val.data(), 4);
        } else if (val.size() == 5) {
            // 5-byte write: float (4 bytes LE) + channel index (1 byte)
            memcpy(&f, val.data(), 4);
            ch = val.data()[4];
        } else {
            return;  // Ignore writes that don't match either format
        }

        // Clamp to valid range — protect against NaN, negatives, and >1.0
        if (isnan(f) || f < 0.0f) f = 0.0f;
        if (f > 1.0f) f = 1.0f;

        set_duty(ch, f);
    }
};


/**
 * Handles reads and writes to the name characteristic.
 *
 * Write a UTF-8 string (1–20 bytes) to rename the device. The new name
 * is saved to NVS and takes effect on the next reboot (BLE stack cannot
 * rename mid-session). Reading returns the current name.
 */
class NameCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* pCharacteristic, NimBLEConnInfo& connInfo) override {
        NimBLEAttValue val = pCharacteristic->getValue();
        size_t len = val.size();

        if (len == 0 || len > MAX_NAME_LEN) {
            dbg("Name rejected: length %d (must be 1-%d)\n", len, MAX_NAME_LEN);
            return;
        }

        // Copy and null-terminate
        memcpy(deviceName, val.data(), len);
        deviceName[len] = '\0';

        // Persist to NVS
        prefs.begin("galvo", false);
        prefs.putString("name", deviceName);
        prefs.end();

        dbg("Name set to '%s' — will take effect on reboot\n", deviceName);

        // Restart the device so the new name takes effect immediately
        dbg("Rebooting...\n");
        delay(500);
        ESP.restart();
    }
};


// ── Arduino Setup ───────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);

#ifdef DEBUG
    // Give the serial monitor time to connect before printing anything
    delay(2000);
#endif

    // ── Load device name from NVS ──
    prefs.begin("galvo", true);  // read-only
    String savedName = prefs.getString("name", DEFAULT_DEVICE_NAME);
    prefs.end();
    strncpy(deviceName, savedName.c_str(), MAX_NAME_LEN);
    deviceName[MAX_NAME_LEN] = '\0';

    dbg("BLE Galvo Controller '%s' (%d channels) ... ", deviceName, NUM_CHANNELS);

    // ── Initialize PWM channels ──
    // Each galvo gets its own LEDC channel at 5 kHz with 10-bit resolution.
    // We use ledcAttach()+ledcWrite() instead of analogWrite() because
    // analogWriteResolution() has a null-pointer crash bug in ESP32 core 3.x
    // when called before the first analogWrite(). See:
    // https://github.com/espressif/arduino-esp32/issues/11670
    for (uint8_t i = 0; i < NUM_CHANNELS; i++) {
        ledcAttach(GALVO_PINS[i], 5000, 10);  // 5 kHz, 10-bit (0–1023)
        ledcWrite(GALVO_PINS[i], 0);           // Start at zero deflection
        duty[i] = 0;
    }

    // ── LED indicator ──
    // Active low: HIGH = off at boot, LOW = on when client connects
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH);

    // ── BLE stack initialization ──
    // NimBLE is a lightweight BLE stack that uses significantly less flash
    // and RAM than the default Arduino BLE library. We create a single
    // service with a writable galvo characteristic and a read/write name
    // characteristic for remote renaming.
    NimBLEDevice::init(deviceName);

    NimBLEServer* pServer = NimBLEDevice::createServer();
    pServer->setCallbacks(new ServerCallbacks());

    NimBLEService* pService = pServer->createService(SERVICE_UUID);

    // Galvo control characteristic (write-only)
    NimBLECharacteristic* pGalvoChar = pService->createCharacteristic(
        CHARACTERISTIC_UUID, NIMBLE_PROPERTY::WRITE
    );
    pGalvoChar->setValue(0.0f);
    pGalvoChar->setCallbacks(new GalvoCallbacks());

    // Name characteristic (read + write)
    NimBLECharacteristic* pNameChar = pService->createCharacteristic(
        NAME_CHARACTERISTIC_UUID, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE
    );
    pNameChar->setValue((uint8_t*)deviceName, strlen(deviceName));
    pNameChar->setCallbacks(new NameCallbacks());

    pService->start();

    // ── Start advertising ──
    // The service UUID is included in the advertisement so clients can
    // filter by it during scanning (important because the device name
    // often gets truncated out of the 31-byte ad packet).
    NimBLEAdvertising* pAdvertising = NimBLEDevice::getAdvertising();
    pAdvertising->addServiceUUID(SERVICE_UUID);
    pAdvertising->setName(deviceName);
    pAdvertising->start();

    dbg("ready!\n");
}


// ── Arduino Main Loop ───────────────────────────────────────────────────────

// Nothing to do here — all work happens in BLE callbacks. The delay keeps
// the watchdog happy and prevents the idle task from being starved.
void loop() {
    delay(1000);
}
