#include "BleOta.h"
#include <NimBLEDevice.h>
#include <Update.h>

BleOta bleOta;

static NimBLECharacteristic* controlChar = nullptr;
static uint32_t otaExpectedSize = 0;
static uint32_t otaReceivedSize = 0;
static int otaLastPercent = -1;
static bool otaInProgress = false;

// Default callbacks
static void defaultProgress(int percent) {
    if (percent == 0) Serial.printf("OTA progress: ");
    if (percent % 5 == 0) Serial.printf(".");
}

static void defaultComplete() {
    Serial.println("\nOTA update complete, restarting...");
}

static void (*progressCallback)(int) = defaultProgress;
static void (*completeCallback)() = defaultComplete;

// --- BLE Callbacks ---

class OtaServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo) override {
        Serial.println("BLE client connected");
    }

    void onDisconnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo, int reason) override {
        Serial.println("BLE client disconnected");
        if (otaInProgress) {
            Update.abort();
            otaInProgress = false;
            Serial.println("OTA aborted: client disconnected");
        }
        NimBLEDevice::startAdvertising();
    }
};

class OtaControlCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* pCharacteristic, NimBLEConnInfo& connInfo) override {
        NimBLEAttValue value = pCharacteristic->getValue();
        if (value.size() < 1) return;

        const uint8_t* data = value.data();
        uint8_t cmd = data[0];

        switch (cmd) {
            case OTA_CMD_START: {
                if (value.size() >= 5) {
                    otaExpectedSize = (uint32_t)data[1] |
                                     ((uint32_t)data[2] << 8) |
                                     ((uint32_t)data[3] << 16) |
                                     ((uint32_t)data[4] << 24);

                    if (otaExpectedSize == 0) {
                        Serial.println("OTA rejected: firmware size is 0");
                        uint8_t nack = OTA_CMD_NACK;
                        controlChar->setValue(&nack, 1);
                        controlChar->notify();
                        break;
                    }

                    if (Update.begin(otaExpectedSize)) {
                        otaInProgress = true;
                        otaReceivedSize = 0;
                        otaLastPercent = -1;
                        Serial.printf("OTA started, expecting %u bytes\n", otaExpectedSize);
                        uint8_t ack = OTA_CMD_ACK;
                        controlChar->setValue(&ack, 1);
                        controlChar->notify();
                    } else {
                        Serial.println("OTA begin failed");
                        uint8_t nack = OTA_CMD_NACK;
                        controlChar->setValue(&nack, 1);
                        controlChar->notify();
                    }
                }
                break;
            }
            case OTA_CMD_END: {
                if (otaInProgress) {
                    if (Update.end(true)) {
                        Serial.println("OTA complete, rebooting...");
                        uint8_t ack = OTA_CMD_ACK;
                        controlChar->setValue(&ack, 1);
                        controlChar->notify();
                        if (completeCallback) completeCallback();
                        Serial.flush();
                        delay(1500);  // let BLE stack flush the ACK
                        ESP.restart();
                    } else {
                        Serial.printf("OTA failed: %s\n", Update.errorString());
                        uint8_t nack = OTA_CMD_NACK;
                        controlChar->setValue(&nack, 1);
                        controlChar->notify();
                    }
                    otaInProgress = false;
                }
                break;
            }
            case OTA_CMD_ABORT: {
                if (otaInProgress) {
                    Update.abort();
                    otaInProgress = false;
                    Serial.println("OTA aborted by client");
                }
                break;
            }
        }
    }
};

class OtaDataCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* pCharacteristic, NimBLEConnInfo& connInfo) override {
        if (!otaInProgress) return;

        NimBLEAttValue value = pCharacteristic->getValue();
        if (value.size() == 0) return;

        size_t written = Update.write((uint8_t*)value.data(), value.size());
        if (written != value.size()) {
            Serial.printf("OTA write error: wrote %u of %u bytes\n",
                          (unsigned)written, (unsigned)value.size());
            return;
        }

        otaReceivedSize += value.size();

        if (progressCallback && otaExpectedSize > 0) {
            int percent = (otaReceivedSize * 100) / otaExpectedSize;
            if (percent != otaLastPercent) {
                otaLastPercent = percent;
                progressCallback(percent);
            }
        }
    }
};

// --- BleOta implementation ---

void BleOta::begin(const char* deviceName) {
    // Check if sketch already set up BLE (has a server)
    bool alreadyRunning = (NimBLEDevice::getServer() != nullptr);

    // Safe to call multiple times — returns immediately if already initialized
    NimBLEDevice::init(deviceName);

    NimBLEServer* server = NimBLEDevice::createServer();

    // Only set server callbacks if we own the BLE stack
    // (sketch hasn't already set up its own server)
    if (!alreadyRunning) {
        server->setCallbacks(new OtaServerCallbacks());
    }

    NimBLEService* service = server->createService(NimBLEUUID(BLE_OTA_SERVICE_UUID));

    controlChar = service->createCharacteristic(
        NimBLEUUID(BLE_OTA_CHAR_CONTROL_UUID),
        NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::NOTIFY
    );
    controlChar->setCallbacks(new OtaControlCallbacks());

    NimBLECharacteristic* dataChar = service->createCharacteristic(
        NimBLEUUID(BLE_OTA_CHAR_DATA_UUID),
        NIMBLE_PROPERTY::WRITE_NR
    );
    dataChar->setCallbacks(new OtaDataCallbacks());

    service->start();

    if (!alreadyRunning) {
        NimBLEAdvertisementData advData;
        advData.setName(deviceName);
        advData.addServiceUUID(NimBLEUUID(BLE_OTA_SERVICE_UUID));

        NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
        advertising->setAdvertisementData(advData);
        NimBLEDevice::startAdvertising();

        Serial.printf("BLE OTA ready, advertising as '%s'\n", deviceName);
    } else {
        // Add OTA service UUID to advertising data — caller starts advertising
        NimBLEDevice::getAdvertising()->addServiceUUID(NimBLEUUID(BLE_OTA_SERVICE_UUID));
        Serial.println("BLE OTA service added");
    }
}

void BleOta::handle() {
    // Handle OTA abort on disconnect when sketch owns the BLE callbacks
    if (otaInProgress) {
        NimBLEServer* server = NimBLEDevice::createServer();
        if (server->getConnectedCount() == 0) {
            Update.abort();
            otaInProgress = false;
            Serial.println("OTA aborted: client disconnected");
        }
    }
}

bool BleOta::isUpdating() {
    return otaInProgress;
}

void BleOta::onProgress(void (*callback)(int percent)) {
    progressCallback = callback;
}

void BleOta::onComplete(void (*callback)()) {
    completeCallback = callback;
}
