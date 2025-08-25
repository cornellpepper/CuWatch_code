cmake_minimum_required(VERSION 3.13)

set(CMAKE_C_COMPILER "arm-none-eabi-gcc")
#set(PICO_COMPILER "arm-none-eabi-gcc")
set(PICO_BOARD "pico_w")
set(PICO_PLATFORM "rp2040")

set(picotool_DIR $HOME/src/picotool)

include(pico_sdk_import.cmake)


project(main_project C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
pico_sdk_init()
add_executable(main
    main.c
)
target_include_directories(main PRIVATE
        ${CMAKE_CURRENT_LIST_DIR}
        )

pico_enable_stdio_usb(main 1)
pico_enable_stdio_uart(main 1)
pico_set_program_name(main "main")
pico_set_program_version(main "0.1")
pico_set_program_description(main "CuWatch main application")
target_compile_definitions(main PRIVATE PICO_ADC_ENABLE)

pico_add_extra_outputs(main)

target_link_libraries(main 
                      hardware_adc 
                      hardware_spi 
                      pico_cyw43_arch_lwip_threadsafe_background 
                      pico_multicore
                      pico_util
                      pico_time
                      pico_stdlib)