
/**
 * Copyright (c) 2022 Raspberry Pi (Trading) Ltd.
 *
 * SPDX-License-Identifier: BSD-3-Clause
 */

 #include <cyw43_configport.h>
#include <pico/time.h>
#include <pico/types.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "pico/util/queue.h"
#include "pico/time.h"
#include "pico/cyw43_arch.h"
#include "hardware/gpio.h"
#include "hardware/adc.h"
#include "hardware/spi.h"

#define WIFI_SSID "your_wifi_ssid"  // Replace with your WiFi SSID
#define WIFI_PASSWORD "your_wifi_password"  // Replace with your WiFi password

#define ADC_SIPM_THRESHOLD 1000  // Define a threshold for SiPM ADC value to trigger data collection
#define ADC_SIPM_RESET_THRESHOLD (ADC_SIPM_THRESHOLD - 100)  // Define a threshold for Temperature ADC value to trigger data collection

void collect_data(void) 
{
    // This function will collect data from the ADC and send it via MQTT
    // Implement your data collection logic here
    // For example, read ADC values and push them to the FIFO for the main core to process


    while (true) {
        adc_select_input(0);  // Select ADC input 0 (SiPM)
        uint16_t adc_value_sipm = adc_read();  // Read SiPM ADC value
        if ( adc_value_sipm > ADC_SIPM_THRESHOLD ) { // signal is above threshold
            // we have triggered; measure the current time
            absolute_time_t trigger_time = get_absolute_time();
            // wait till be drop below the reset threshold
            while (adc_value_sipm > ADC_SIPM_THRESHOLD) {
                adc_value_sipm = adc_read();  // Read SiPM ADC value again. Conversion takes like 80 clocks
                if (adc_value_sipm < ADC_SIPM_RESET_THRESHOLD) {
                    // If the SiPM ADC value drops below the reset threshold, we can stop collecting data
                    break;
                }
                sleep_us(3); // sleep for 3 us 
            }
            // time difference for drop
            uint32_t time_diff = absolute_time_diff_us(trigger_time, get_absolute_time());
            // If the SiPM ADC value exceeds a certain threshold, trigger the data collection
            multicore_fifo_push_blocking(adc_value_sipm);  // Push the SiPM ADC value to the FIFO
            printf("SiPM ADC Value: %d\n", adc_value_sipm);
        }

        // now that we have triggered, read the temperature sensor and 
        // prepare the data to send
        adc_select_input(1);  // Select ADC input 1 (Temperature)
        uint16_t adc_value_temp = adc_read();  // Read Temperature ADC value


        printf("SiPM ADC Value: %d\n", adc_value_sipm);
        printf("Temperature ADC Value: %d\n", adc_value_temp);
    }
    __builtin_unreachable();
}

queue_t message_queue;  // Queue to hold messages for the main core

typedef struct {
    uint16_t sipm_value;  // SiPM ADC value
    uint16_t temp_value;  // Temperature ADC value
    uint32_t timestamp;  // Timestamp of the data collection
    uint32_t time_diff;  // Time difference for the drop in SiPM ADC value
} message_t;

int main(void) 
{
    // Initialize the standard input/output library
    // This is necessary for printing debug messages to the console
    // and for using the cyw43_arch functions.
    stdio_init_all();
    if (cyw43_arch_init()) {
        printf("Wi-Fi init failed");
        return -1;
    }
    // initialize the ADC
    adc_init();
    adc_gpio_init(26);  // Initialize GPIO 26 for ADC0 input -- SiPM
    adc_gpio_init(27);  // Initialize GPIO 27 for ADC1 input -- Temperature
    // Enable GPIO pin 19 for output (enable for HV)
    gpio_init(19);
    gpio_set_dir(19, GPIO_OUT);
    gpio_put(19, 1);  // Set GPIO 19 high to enable the HV power supply
    // check if we are in coincidence mode
    gpio_init(14);  // Initialize GPIO 14 for coincidence mode
    if (getenv("COINCIDENCE_MODE") != NULL) { // this should check a file in the FS
        gpio_set_dir(14, GPIO_OUT);
        gpio_put(14, 1);  // Set GPIO 14 high to enable coincidence mode
    }
    else {
        gpio_set_dir(14, GPIO_IN);
        gpio_pull_up(14);  // Set GPIO 14 as input with pull-up resistor
    }

    // Enable SPI for the SD card
    spi_init(spi0, 12500000);  // Initialize SPI0 at 12.5 MHz
    gpio_set_function(2, GPIO_FUNC_SPI);  // SPI0 SCK
    gpio_set_function(3, GPIO_FUNC_SPI);  // SPI0 TX
    gpio_set_function(0, GPIO_FUNC_SPI);  // SPI0 RX

    // initialize the queue
    queue_init(&message_queue, sizeof(message_t), 16);  // Initialize the

    // we'll be connecting to an access point, not creating one
    cyw43_arch_enable_sta_mode();

    // WiFi credentials are taken from cmake/credentials.cmake
    // create it based on cmake/credentials.cmake.example if you haven't already!
    if (cyw43_arch_wifi_connect_timeout_ms(WIFI_SSID, WIFI_PASSWORD, CYW43_AUTH_WPA2_AES_PSK, 30000)) {
        return 1;
    }

    // start the data collection thread
    multicore_reset_core1();  // Reset core 1 to ensure it's in a clean state
    multicore_launch_core1(collect_data);

    while (true) { // this loop will send the MQTT messages, eventually
        cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, 1);
        sleep_ms(250);
        cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, 0);
        sleep_ms(250);
        // // uint16_t adc_value_sipm = adc_values & 0xFFFF;  // Extract SiPM ADC value
        // // uint16_t adc_value_temp = (adc_values >> 16) & 0xFFFF;  // Extract Temperature ADC value
        // printf("SiPM ADC Value: %d\n", adc_value_sipm);
        // printf("Temperature ADC Value: %d\n", adc_value_temp);
    }
}

