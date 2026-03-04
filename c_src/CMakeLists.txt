cmake_minimum_required(VERSION 3.13)

# Board selection — override from command line: cmake -DPICO_BOARD=pico2_w ..
# Pico-W  = RP2040 (2MB flash, 1MB per OTA slot)
# Pico2-W = RP2350 (4MB flash, 2MB per OTA slot)
# NOTE: Pico2-W requires a FreeRTOS-Kernel version with RP2350 port support.
set(PICO_BOARD "pico_w" CACHE STRING "Target board: pico_w (RP2040) or pico2_w (RP2350)")

# Import pico-sdk (set PICO_SDK_PATH env var or pass -DPICO_SDK_PATH=...)
include($ENV{PICO_SDK_PATH}/external/pico_sdk_import.cmake)

# Import FreeRTOS-Kernel for RP2040/RP2350
set(FREERTOS_KERNEL_PATH ${CMAKE_CURRENT_LIST_DIR}/lib/FreeRTOS-Kernel
    CACHE STRING "Path to FreeRTOS-Kernel")
include(${FREERTOS_KERNEL_PATH}/portable/ThirdParty/GCC/RP2040/FreeRTOS_Kernel_import.cmake)

project(cuwatch C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

# ----------------------------------------------------------------
# FatFS SD card library (INTERFACE — user must provide hw_config.c)
# The hardware config is implemented in src/sdcard.c
# ----------------------------------------------------------------
add_subdirectory(lib/no-OS-FatFS-SD-SDIO-SPI-RPi-Pico/src fatfs_build)

# ----------------------------------------------------------------
# Main firmware executable
# ----------------------------------------------------------------
add_executable(cuwatch
    src/main.c
    src/adc.c
    src/sdcard.c
    src/ring_buffer.c
    src/mqtt.c
    lib/mongoose/mongoose.c      # Single-file Mongoose library
)

target_include_directories(cuwatch PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}         # FreeRTOSConfig.h, lwipopts.h,
                                      # mongoose_config.h, my_secrets.h
    ${CMAKE_CURRENT_LIST_DIR}/src     # gpio_pins.h, cuwatch_types.h
    ${CMAKE_CURRENT_LIST_DIR}/lib/mongoose  # mongoose.h
)

# Flash size define used by Mongoose OTA (also defined in pico-sdk board files,
# but explicit here ensures correct slot sizing).
# PICO_BOARD_STR is printed in main.c startup banner.
if(PICO_BOARD STREQUAL "pico2_w")
    target_compile_definitions(cuwatch PRIVATE
        PICO_FLASH_SIZE_BYTES=4194304   # 4MB — 2MB per OTA slot
        PICO_BOARD_STR="pico2_w"
    )
else()
    target_compile_definitions(cuwatch PRIVATE
        PICO_FLASH_SIZE_BYTES=2097152   # 2MB — 1MB per OTA slot
        PICO_BOARD_STR="pico_w"
    )
endif()

target_link_libraries(cuwatch
    pico_stdlib
    pico_rand                              # Required by Mongoose arch_picosdk.h
    pico_multicore                         # multicore_launch_core1
    hardware_adc                           # ADC sampling
    hardware_gpio                          # GPIO init/IRQ
    hardware_flash                         # Required by Mongoose OTA (pico OTA)
    hardware_watchdog                      # watchdog_reboot() for new_run reset
    pico_cyw43_arch_lwip_sys_freertos      # WiFi + lwIP with FreeRTOS
    FreeRTOS-Kernel                        # FreeRTOS core
    FreeRTOS-Kernel-Heap4                  # FreeRTOS heap4 allocator
    no-OS-FatFS-SD-SDIO-SPI-RPi-Pico      # FatFS SD (brings hardware_spi, hardware_dma)
)

# Generate .uf2, .hex, .bin, .map outputs
pico_add_extra_outputs(cuwatch)

# Route stdio to USB serial (for debug output)
pico_enable_stdio_usb(cuwatch 1)
pico_enable_stdio_uart(cuwatch 0)

# Prevent aggressive loop optimization that can break Mongoose's OTA flash writes
target_compile_options(cuwatch PRIVATE -fno-tree-loop-distribute-patterns)

# ----------------------------------------------------------------
# Build instructions (for reference):
#
#   cd c_src
#   mkdir build && cd build
#
#   For Pico-W (RP2040):
#     cmake -G "Unix Makefiles" -DPICO_BOARD=pico_w ..
#
#   For Pico2-W (RP2350):
#     cmake -G "Unix Makefiles" -DPICO_BOARD=pico2_w ..
#
#   make -j4
#
#   Output: build/cuwatch.uf2  (flash via USB drag-and-drop or picotool)
# ----------------------------------------------------------------
