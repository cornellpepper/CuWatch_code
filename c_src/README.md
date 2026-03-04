# CuWatch C Firmware

C port of the MicroPython muon detector DAQ for the Raspberry Pi Pico-W / Pico2-W
on the Pepper V2 carrier board. Uses:

- **pico-sdk** — hardware drivers and WiFi (CYW43)
- **FreeRTOS** — Core 0 task scheduler (io_task)
- **Mongoose** — MQTT client, SNTP, HTTP OTA firmware update
- **no-OS-FatFS-SD-SDIO-SPI-RPi-Pico** — FatFS on SPI SD card

## Prerequisites

### Required

- **pico-sdk 2.x** — set `PICO_SDK_PATH` environment variable
  ```
  export PICO_SDK_PATH=/path/to/pico-sdk
  ```
- **CMake ≥ 3.13**
- **GNU ARM toolchain** (`arm-none-eabi-gcc`)
- **make** (not ninja)

### Git submodules

Initialize submodules after cloning the repo:

```bash
git submodule update --init --recursive
```

This pulls in:
- `c_src/lib/mongoose` — Mongoose networking library
- `c_src/lib/no-OS-FatFS-SD-SDIO-SPI-RPi-Pico` — SD card FatFS
- `c_src/lib/FreeRTOS-Kernel` — FreeRTOS for RP2040

## Build

```bash
cd c_src

# Copy and fill in WiFi/MQTT credentials
cp my_secrets.h.template my_secrets.h
# Edit my_secrets.h with your WiFi SSID/password and MQTT broker

mkdir build && cd build

# For Pico-W (RP2040) — default
cmake -G "Unix Makefiles" -DPICO_BOARD=pico_w ..

# OR for Pico2-W (RP2350) — see note below
cmake -G "Unix Makefiles" -DPICO_BOARD=pico2_w ..

make -j4
```

Output: `build/cuwatch.uf2`

### Flashing

Hold BOOTSEL button on the Pico-W, plug in USB, release BOOTSEL.
Drag `cuwatch.uf2` to the mounted RPI-RP2 USB drive.

Or use picotool:

```bash
picotool load build/cuwatch.uf2 && picotool reboot
```

## SD Card Setup

Format a MicroSD card as FAT32 and create these files:

| File | Contents | Purpose |
|------|----------|---------|
| `id.txt` | Integer (e.g. `3`) | Device number for MQTT topics |
| `is_secondary` | Any text | Marks node as follower (absent = leader) |

## MQTT Topics

| Topic | Direction | Format |
|-------|-----------|--------|
| `telemetry/NNN` | Pico → Broker | JSON muon event |
| `status/NNN` | Pico → Broker | JSON status (every 30s) |
| `control/NNN/set` | Broker → Pico | JSON control commands |

Where `NNN` is the zero-padded device ID from `id.txt`.

### Control commands (JSON)

```json
{ "threshold": 50000 }              // Update ADC detection threshold
{ "reset_threshold": 33950 }        // Update dead-time reset level
{ "new_run": true }                 // Restart data collection
{ "shutdown": true }                // Stop firmware
{ "make_leader": true }             // Set this node as leader (reads coincidence)
{ "make_leader": false }            // Set this node as follower (drives coincidence)
```

## OTA Firmware Update

The firmware runs an HTTP server on port 8080. To update:

```bash
SIZE=$(wc -c < build/cuwatch.uf2)
curl -X POST "http://<pico-ip>:8080/ota?offset=0&total=$SIZE" \
     --data-binary @build/cuwatch.uf2
```

The Pico will automatically reboot into the new firmware after a successful upload.

## Architecture

```
Core 0 (FreeRTOS io_task)         Core 1 (bare-metal)
─────────────────────────         ───────────────────
WiFi (CYW43 + lwIP)               ADC sampling loop
Mongoose event loop               Pin 26 (SiPM) → adc_read()
 ├─ SNTP timer (hourly)           Threshold detection
 ├─ MQTT reconnect timer          Dead-time handling
 ├─ HTTP OTA (port 8080)          Coincidence pin I/O
 └─ mg_mgr_poll(10ms)             Pushes muon_event_t
                                  Polls control_cmd_t
        ◄──── event_queue (64 entries) ────
        ─────── cmd_queue (8 entries) ────►
```

## Source Files

| File | Description |
|------|-------------|
| `src/main.c` | Entry point: init, Core1 launch, FreeRTOS start |
| `src/adc.c/h` | ADC calibration + Core1 detection loop |
| `src/mqtt.c/h` | Mongoose MQTT + WiFi + OTA (Core0 io_task) |
| `src/sdcard.c/h` | FatFS hw_config + CSV logging |
| `src/ring_buffer.c/h` | Float circular buffer for rate calculation |
| `src/cuwatch_types.h` | Shared data structures |
| `src/gpio_pins.h` | GPIO pin number constants |
| `FreeRTOSConfig.h` | FreeRTOS tuning |
| `lwipopts.h` | lwIP tuning |
| `mongoose_config.h` | Mongoose compile options |
| `my_secrets.h` | WiFi/MQTT credentials (gitignored, copy from template) |

## Notes on Pico2-W (RP2350) Support

The FreeRTOS-Kernel submodule (v10.x) only includes the RP2040 port.
For Pico2-W support, you may need to update the FreeRTOS-Kernel submodule
to a version that includes the RP2350 ARM NTZ port:

```bash
cd c_src/lib/FreeRTOS-Kernel
git fetch && git checkout <version-with-rp2350-support>
```

Alternatively, use the FreeRTOS-Kernel version bundled with pico-sdk 2.x by
setting `FREERTOS_KERNEL_PATH` to the pico-sdk's bundled copy.

The Mongoose OTA (`MG_OTA_PICOSDK`) and all other code is compatible with
both RP2040 and RP2350 without modification.
