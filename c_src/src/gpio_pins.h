#pragma once

/*
 * GPIO pin assignments for the Pepper V2 carrier board with Raspberry Pi Pico-W.
 * These match the MicroPython implementation in src/asynchio5.py.
 */

/* SiPM muon detector ADC input */
#define PIN_SIPM_ADC     26 /* GP26 = ADC0 */
#define ADC_CHANNEL_SIPM 0

/* Temperature sensor ADC input */
#define PIN_TEMP_ADC     27 /* GP27 = ADC1 */
#define ADC_CHANNEL_TEMP 1

/* Coincidence detection pin
 * Leader node:   configured as INPUT — reads HIGH when follower detects a muon
 * Follower node: configured as OUTPUT — driven HIGH during muon dead-time window
 */
#define PIN_COINCIDENCE 14

/* Pepper baseboard LED (LED2) — blinks during calibration; flashes on event */
#define PIN_LED2 15

/* High-voltage power supply enable — active HIGH */
#define PIN_HV_ENABLE 19

/* User switch — active HIGH (PULL_DOWN), triggers clean shutdown on rising edge */
#define PIN_USER_SWITCH 16

/* SPI0 for MicroSD card */
#define PIN_SPI0_RX  0 /* MISO */
#define PIN_SPI0_CS  1 /* Chip Select */
#define PIN_SPI0_SCK 2 /* Clock */
#define PIN_SPI0_TX  3 /* MOSI */

/*
 * Onboard Pico-W LED (WiFi chip GPIO):
 *   cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, 1);  // on
 *   cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, 0);  // off
 */
