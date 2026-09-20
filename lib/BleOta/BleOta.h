#ifndef BLE_OTA_H
#define BLE_OTA_H

#include <Arduino.h>

#ifndef BLE_DEVICE_NAME
#define BLE_DEVICE_NAME "ESP32_BLE_OTA"
#endif

// BLE OTA Service and Characteristic UUIDs
#define BLE_OTA_SERVICE_UUID       ((uint16_t)0xFF10)
#define BLE_OTA_CHAR_CONTROL_UUID  ((uint16_t)0xFF11)
#define BLE_OTA_CHAR_DATA_UUID     ((uint16_t)0xFF12)

// OTA Control commands
#define OTA_CMD_START  0x01
#define OTA_CMD_END    0x02
#define OTA_CMD_ACK    0x03
#define OTA_CMD_NACK   0x04
#define OTA_CMD_ABORT  0x05

class BleOta {
public:
    // Initialize BLE OTA service.
    // - Simple sketches: bleOta.begin() initializes NimBLE and starts advertising.
    // - Sketches with own BLE: call NimBLEDevice::init(), create your server
    //   and services, THEN call bleOta.begin() BEFORE starting advertising.
    //   It detects the existing stack, adds the OTA service and UUID to
    //   advertising, but leaves advertising control to the sketch.
    void begin(const char* deviceName = BLE_DEVICE_NAME);

    // Call in loop() to handle OTA events
    void handle();

    // Check if OTA update is in progress
    bool isUpdating();

    // Override default progress callback (default prints dots every 5%)
    void onProgress(void (*callback)(int percent));

    // Override default completion callback (default prints message)
    void onComplete(void (*callback)());
};

extern BleOta bleOta;

#endif
