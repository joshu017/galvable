#include <NimBLEDevice.h>
#include "esp32-hal-bt-mem.h"  // Prevent Arduino core from releasing BT memory before setup()

// Uncomment to enable debug output (Serial.flush after each print, boot delay)
// #define DEBUG

#define LED_PIN 8 // built-in LED pin on the esp32c3 supermini board (active low)
#define GALVO_PIN 4 // PWM output to galvanometer
#define DEVICE_NAME "GalvoCtrl"
#define SERVICE_UUID        "e0f3a8b1-4c6d-4e9f-8b2a-7d1c5f3e9a0b"
#define CHARACTERISTIC_UUID "a1b2c3d4-5e6f-7890-abcd-ef1234567890"

#ifdef DEBUG
#define dbg(fmt, ...) do { Serial.printf(fmt, ##__VA_ARGS__); Serial.flush(); } while(0)
#else
#define dbg(fmt, ...) Serial.printf(fmt, ##__VA_ARGS__)
#endif

int duty;

void set_duty(float f) {
    duty = (int)(f * 1000.0f);
    ledcWrite(GALVO_PIN, duty);
    dbg("Set duty: %.4f -> duty %d\n", f, duty);
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
        if (val.size() == 4) {
            float f;
            memcpy(&f, val.data(), 4);

            if (isnan(f) || f < 0.0f) f = 0.0f;
            if (f > 1.0f) f = 1.0f;

            set_duty(f);
        }
    }
};

void setup() {
    Serial.begin(115200);
#ifdef DEBUG
    delay(2000);
#endif
    dbg("BLE Galvo Controller ... ");

    ledcAttach(GALVO_PIN, 5000, 10); // 5kHz, 10-bit resolution (0-1023, we use 0-1000)
    ledcWrite(GALVO_PIN, 0);

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
