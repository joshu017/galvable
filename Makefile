SHELL := /bin/sh
.DEFAULT_GOAL := build
ARDUINO_CLI ?= arduino-cli
PYTHON ?= python3
BOARD_OPTIONS ?= PartitionScheme=min_spiffs,CDCOnBoot=cdc
FQBN := esp32:esp32:esp32c3:$(BOARD_OPTIONS)
BUILD_DIR := $(CURDIR)/build
UPLOAD_PORT ?=
UPLOAD_SPEED ?= 921600
BLE_DEVICE_NAME ?=
BLE_DEVICE_ADDRESS ?=
ESP32_CORE_VERSION ?= 3.3.10
NIMBLE_VERSION ?= 2.3.8
# Preserve the parent framework's compilation flags.
EXTRA_CPP_FLAGS ?= -fpermissive
EXTRA_C_FLAGS ?=

.PHONY: help setup build flash ble monitor ports clean
help:
	@echo 'Galvable (ESP32-C3 only)'
	@echo '  setup        Install pinned Arduino core and NimBLE library'
	@echo '  build        Compile firmware (default); no device access'
	@echo '  ports        List USB ports'
	@echo '  flash        Build/upload; requires UPLOAD_PORT=/dev/cu.usbmodem...'
	@echo '  ble          Build/upload OTA; requires BLE_DEVICE_ADDRESS=... or BLE_DEVICE_NAME=...'
	@echo '  monitor      Serial monitor; requires UPLOAD_PORT=...'
	@echo '  clean        Delete local build artifacts'
	@echo 'Overrides: ARDUINO_CLI, PYTHON, BOARD_OPTIONS, UPLOAD_PORT, UPLOAD_SPEED,'
	@echo '           BLE_DEVICE_ADDRESS, BLE_DEVICE_NAME, ESP32_CORE_VERSION, NIMBLE_VERSION,'
	@echo '           EXTRA_CPP_FLAGS, EXTRA_C_FLAGS'
setup:
	$(ARDUINO_CLI) core update-index --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
	$(ARDUINO_CLI) core install esp32:esp32@$(ESP32_CORE_VERSION) --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
	$(ARDUINO_CLI) lib install "NimBLE-Arduino@$(NIMBLE_VERSION)"
build:
	$(ARDUINO_CLI) compile --fqbn "$(FQBN)" --library "$(CURDIR)/lib/BleOta" --build-path "$(BUILD_DIR)" --build-property "compiler.cpp.extra_flags=$(EXTRA_CPP_FLAGS)" --build-property "compiler.c.extra_flags=$(EXTRA_C_FLAGS)" "$(CURDIR)/galvable"
flash:
	@test -n "$(UPLOAD_PORT)" || { echo 'Set UPLOAD_PORT (use make ports to list devices).'; exit 1; }
	$(MAKE) build
	$(ARDUINO_CLI) upload --fqbn "$(FQBN)" --port "$(UPLOAD_PORT)" --upload-property upload.speed=$(UPLOAD_SPEED) --input-dir "$(BUILD_DIR)" "$(CURDIR)/galvable"
ble:
	@test -n "$(BLE_DEVICE_ADDRESS)$(BLE_DEVICE_NAME)" || { echo 'Set BLE_DEVICE_ADDRESS or BLE_DEVICE_NAME to the intended OTA device.'; exit 1; }
	$(MAKE) build
	$(PYTHON) scripts/ble_ota_upload.py --firmware "$(BUILD_DIR)/galvable.ino.bin" $(if $(BLE_DEVICE_ADDRESS),--address "$(BLE_DEVICE_ADDRESS)",--name "$(BLE_DEVICE_NAME)")
monitor:
	@test -n "$(UPLOAD_PORT)" || { echo 'Set UPLOAD_PORT (use make ports to list devices).'; exit 1; }
	$(ARDUINO_CLI) monitor --port "$(UPLOAD_PORT)" --config baudrate=115200
ports:
	$(ARDUINO_CLI) board list
clean:
	rm -rf "$(CURDIR)/build"
