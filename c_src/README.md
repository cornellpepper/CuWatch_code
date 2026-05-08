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

Output: `build/cuwatch.uf2` (for initial flash) and `build/cuwatch.bin` (for OTA)

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

### Telemetry payload fields

Every event:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `device_number` | int | Device ID from `id.txt` |
| `muon_count` | uint | Cumulative muon count for this run |
| `adc_v` | uint | SiPM ADC reading (16-bit scaled, 0–65520) |
| `temp_adc_v` | uint | Temperature ADC reading (16-bit scaled) |
| `dt` | uint | ms since previous muon event |
| `ts` | string | ISO 8601 UTC timestamp (`…Z`); `1970-…` if NTP not yet synced |
| `t_ms` | uint | Monotonic `to_ms_since_boot` time of detection |
| `wait_cnt` | uint | Dead-time counter remaining when signal dropped (0 = timed out) |
| `coincidence` | uint | 1 if coincidence detected (leader only), else 0 |

First event only (run metadata):

| Field | Type | Description |
| ----- | ---- | ----------- |
| `run_start` | string | ISO 8601 UTC timestamp of run start |
| `baseline` | int | Calibrated ADC noise floor (16-bit counts) |
| `threshold` | int | Detection threshold (16-bit counts) |
| `reset_threshold` | int | Dead-time exit level (16-bit counts) |
| `is_leader` | bool | true = reads coincidence pin; false = drives it |

### Status payload fields

Published every 30 seconds:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `rate` | float | Current muon rate (Hz), averaged over last 50 events |
| `muon_count` | uint | Cumulative muon count |
| `threshold` | int | Current detection threshold |
| `reset_threshold` | int | Current dead-time exit level |
| `baseline` | float | Calibrated ADC noise floor |
| `runtime` | float | Seconds since run start |
| `is_leader` | bool | Leader/follower mode |
| `avg_time_ms` | float | **Always 0** — Core 1 loop timing is not currently measured |

### Control commands (JSON)

```json
{ "threshold": 50000 }              // Update ADC detection threshold
{ "reset_threshold": 33950 }        // Update dead-time reset level
{ "new_run": true }                 // Flush SD card and reboot (starts a new run)
{ "shutdown": true }                // Stop firmware cleanly
{ "make_leader": true }             // Set this node as leader (reads coincidence)
{ "make_leader": false }            // Set this node as follower (drives coincidence)
```

`new_run` triggers a watchdog reboot (equivalent to the MicroPython `machine.reset()`).
The device re-calibrates, reconnects to WiFi/MQTT, and begins a new CSV file on restart.

## OTA Firmware Update

The firmware runs an HTTP server on port 8080 that accepts the Mongoose multi-POST
chunked OTA protocol. Use the provided helper script — **do not use a single `curl`
call**, as the binary must be split into 4 KB chunks:

```bash
python3 c_src/ota_upload.py <pico-ip> build/cuwatch.bin
```

Upload `cuwatch.bin` (raw binary), **not** `cuwatch.uf2`.

The device reboots automatically into the new firmware after the final chunk is received.

To find the Pico's IP address, check your router's DHCP table or watch the USB
serial output at boot.

## Architecture

```
Core 0 (FreeRTOS io_task)         Core 1 (bare-metal)
─────────────────────────         ───────────────────
WiFi (CYW43 + lwIP)               ADC sampling loop
Mongoose event loop               Pin 26 (SiPM) → adc_read()
 ├─ SNTP timer (10s → hourly)     Threshold detection
 ├─ MQTT reconnect timer (3s)     Dead-time handling
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
| `ota_upload.py` | OTA upload helper script |

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
