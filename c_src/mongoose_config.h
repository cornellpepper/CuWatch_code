#pragma once

// Mongoose architecture selection: Pico-SDK with lwIP
#define MG_ARCH        MG_ARCH_PICOSDK
#define MG_ENABLE_LWIP 1

// Built-in OTA support for Raspberry Pi Pico (RP2040 and RP2350)
// mg_ota_begin() / mg_ota_write() / mg_ota_end() use flash_range_* from pico-sdk
#define MG_OTA MG_OTA_PICOSDK

// Tune buffer sizes for embedded target.
// MG_MAX_RECV_SIZE must fit HTTP headers (~200 B) + one OTA chunk (4096 B).
#define MG_IO_SIZE       512
#define MG_MAX_RECV_SIZE 8192

// Enable logging (disable by setting MG_ENABLE_LOG 0 for production)
#define MG_ENABLE_LOG 1
