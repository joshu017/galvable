#include <NimBLEDevice.h>
#include "esp32-hal-bt-mem.h"  // Prevent Arduino core from releasing BT memory before setup()

// Uncomment to enable debug output (Serial.flush after each print, boot delay)
// #define DEBUG

#define LED_PIN 8 // built-in LED pin on the esp32c3 supermini board (active low)
#define DEVICE_NAME "GalvoCtrl"
#define SERVICE_UUID        "e0f3a8b1-4c6d-4e9f-8b2a-7d1c5f3e9a0b"
#define CHARACTERISTIC_UUID "a1b2c3d4-5e6f-7890-abcd-ef1234567890"

#ifdef DEBUG
#define dbg(fmt, ...) do { Serial.printf(fmt, ##__VA_ARGS__); Serial.flush(); } while(0)
#else
#define dbg(fmt, ...) Serial.printf(fmt, ##__VA_ARGS__)
#endif

// PWM output pins — one per galvo channel. Array length determines channel count.
static const uint8_t GALVO_PINS[] = {4, 3, 2, 1, 0, 10};
static const uint8_t NUM_CHANNELS = sizeof(GALVO_PINS) / sizeof(GALVO_PINS[0]);

int duty[sizeof(GALVO_PINS) / sizeof(GALVO_PINS[0])];

void set_duty(uint8_t ch, float f) {
    if (ch >= NUM_CHANNELS) {
        dbg("Invalid channel %d (max %d)\n", ch, NUM_CHANNELS - 1);
        return;
    }
    duty[ch] = (int)(f * 1000.0f);
    ledcWrite(GALVO_PINS[ch], duty[ch]);
    dbg("Ch %d: %.4f -> duty %d\n", ch, f, duty[ch]);
}

class ServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo) override {
        dbg("Client connected\n");
        digitalWrite(LED_PIN, LOW);
    }
    void onDisconnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo, int reason) override {
        dbg("Client disconnected (reason=%d) - restarting advertising\n", reason);
        digitalWrite(LED_PIN, HIGH);
        NimBLEDevice::startAdvertising();
    }
};

class GalvoCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* pCharacteristic, NimBLEConnInfo& connInfo) override {
        NimBLEAttValue val = pCharacteristic->getValue();
        float f;
        uint8_t ch = 0;

        if (val.size() == 4) {
            // 4-byte write: float only → channel 0
            memcpy(&f, val.data(), 4);
        } else if (val.size() == 5) {
            // 5-byte write: float (4 bytes LE) + channel index (1 byte)
            memcpy(&f, val.data(), 4);
            ch = val.data()[4];
        } else {
            return; // ignore invalid lengths
        }

        if (isnan(f) || f < 0.0f) f = 0.0f;
        if (f > 1.0f) f = 1.0f;

        set_duty(ch, f);
    }
};

void setup() {
    Serial.begin(115200);
#ifdef DEBUG
    delay(2000);
#endif
    dbg("BLE Galvo Controller (%d channels) ... ", NUM_CHANNELS);

    // Initialize all galvo PWM channels
    for (uint8_t i = 0; i < NUM_CHANNELS; i++) {
        ledcAttach(GALVO_PINS[i], 5000, 10); // 5kHz, 10-bit resolution (0-1023, we use 0-1000)
        ledcWrite(GALVO_PINS[i], 0);
        duty[i] = 0;
    }

    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH);

    NimBLEDevice::init(DEVICE_NAME);
    NimBLEServer* pServer = NimBLEDevice::createServer();
    pServer->setCallbacks(new ServerCallbacks());
    NimBLEService* pService = pServer->createService(SERVICE_UUID);
    NimBLECharacteristic* pCharacteristic = pService->createCharacteristic(
        CHARACTERISTIC_UUID, NIMBLE_PROPERTY::WRITE
    );
    pCharacteristic->setValue(0.0f);
    pCharacteristic->setCallbacks(new GalvoCallbacks());
    pService->start();

    NimBLEAdvertising* pAdvertising = NimBLEDevice::getAdvertising();
    pAdvertising->addServiceUUID(SERVICE_UUID);
    pAdvertising->setName(DEVICE_NAME);
    pAdvertising->start();

    dbg("ready!\n");
}

void loop() {
    delay(1000);
}
