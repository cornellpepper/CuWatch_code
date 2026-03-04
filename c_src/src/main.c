/*
 * CuWatch — Muon Detector DAQ Firmware
 * Raspberry Pi Pico-W (RP2040) / Pico2-W (RP2350) on Pepper V2 baseboard.
 *
 * Architecture:
 *   Core 0: FreeRTOS io_task
 *     - WiFi + MQTT (Mongoose) + HTTP OTA
 *     - Drains event queue → publishes MQTT telemetry + writes CSV
 *
 *   Core 1: Bare-metal ADC detection loop
 *     - Tight SiPM ADC sampling + muon detection
 *     - Pushes muon_event_t to inter-core event_queue
 *     - Polls command_queue for threshold/mode updates
 *
 * Initialization sequence (Core 0 only, before FreeRTOS scheduler):
 *   1. stdio, GPIO pins, HV enable
 *   2. Mount SD card, read device ID + leader status
 *   3. Calibrate ADC baseline (500 samples, ~5s, LED2 blinks)
 *   4. Create CSV file on SD card
 *   5. Init inter-core queues
 *   6. Launch Core 1 ADC loop
 *   7. Create FreeRTOS io_task
 *   8. Start FreeRTOS scheduler
 *
 * CRITICAL: multicore_launch_core1() must be called BEFORE vTaskStartScheduler().
 */

#include "adc.h"
#include "mqtt.h"
#include "sdcard.h"
#include "cuwatch_types.h"
#include "gpio_pins.h"
#include "ring_buffer.h"

#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "pico/time.h"
#include "pico/util/queue.h"
#include "hardware/gpio.h"
#include "hardware/adc.h"

#include "FreeRTOS.h"
#include "task.h"

#include <stdio.h>
#include <string.h>

/* ----------------------------------------------------------------
 * Global state
 * ---------------------------------------------------------------- */

static queue_t g_event_queue;
static queue_t g_command_queue;
static run_config_t g_run_config;
static run_stats_t g_run_stats;

/* Ring buffer storage (Core0 owned) */
static float g_dt_storage[DT_RING_SIZE];
static float g_rate_storage[RATE_RING_SIZE];
static ring_buffer_t g_dts;
static ring_buffer_t g_rates;

/* FreeRTOS task parameters */
static io_task_params_t g_io_params;

/* ----------------------------------------------------------------
 * User switch interrupt handler
 * ---------------------------------------------------------------- */

static void user_switch_isr(uint gpio, uint32_t events)
{
  if (gpio == PIN_USER_SWITCH && (events & GPIO_IRQ_EDGE_RISE)) {
    g_run_config.shutdown_request = true;
    control_cmd_t cmd = {.type = CMD_SHUTDOWN, .value = 0};
    /* queue_try_add is multicore+IRQ safe */
    queue_try_add(&g_command_queue, &cmd);
  }
}

/* ----------------------------------------------------------------
 * Core 1 entry point
 * Must be launched BEFORE vTaskStartScheduler().
 * Runs bare-metal (no FreeRTOS on Core 1).
 * ---------------------------------------------------------------- */

static void core1_entry(void)
{
  /* Allow Core 0 to pause Core 1 during flash OTA writes.
   * flash_range_erase/program cannot run while any core fetches instructions
   * from XIP flash; multicore_lockout_victim_init() installs a SIO interrupt
   * handler that parks Core 1 in SRAM (the bootrom) when Core 0 calls
   * multicore_lockout_start_blocking(). */
  multicore_lockout_victim_init();

  printf("Core1: ADC detection loop starting\n");
  adc_detection_loop(&g_event_queue, &g_command_queue, &g_run_config);
  printf("Core1: ADC detection loop exited\n");
}

/* ----------------------------------------------------------------
 * GPIO initialization
 * ---------------------------------------------------------------- */

static void init_gpio_pins(void)
{
  /* HV power supply enable — active HIGH */
  gpio_init(PIN_HV_ENABLE);
  gpio_set_dir(PIN_HV_ENABLE, GPIO_OUT);
  gpio_put(PIN_HV_ENABLE, 1); /* Off initially; enabled after calibration */

  /* User switch — pull-down, trigger on rising edge */
  gpio_init(PIN_USER_SWITCH);
  gpio_set_dir(PIN_USER_SWITCH, GPIO_IN);
  gpio_pull_down(PIN_USER_SWITCH);
  gpio_set_irq_enabled_with_callback(PIN_USER_SWITCH,
                                     GPIO_IRQ_EDGE_RISE,
                                     true,
                                     user_switch_isr);

  /* LED2 is initialized by adc_calibrate() */
}

/* ----------------------------------------------------------------
 * FreeRTOS io_task wrapper
 * ---------------------------------------------------------------- */

static void io_task(void *pvParams)
{
  mqtt_io_task(pvParams);
  /* mqtt_io_task only returns on shutdown */
  vTaskDelete(NULL);
}

/* ----------------------------------------------------------------
 * main()
 * ---------------------------------------------------------------- */

int main(void)
{
  stdio_init_all();
  sleep_ms(500); /* Brief delay for USB serial to enumerate */

  printf("\n\n=== CuWatch Muon Detector ===\n");
  printf("Board: " PICO_BOARD_STR "\n");
  printf("Compiled: " __DATE__ " " __TIME__ "\n\n");

  /* 1. GPIO */
  init_gpio_pins();

  /* 2. SD card — mount and read configuration */
  if (!sdcard_mount()) {
    printf("ERROR: SD card mount failed. Halting.\n");
    while (true) {
      gpio_xor_mask(1u << PIN_LED2);
      sleep_ms(200);
    }
  }

  memset(&g_run_stats, 0, sizeof(g_run_stats));
  g_run_stats.device_id = sdcard_read_device_id();

  memset(&g_run_config, 0, sizeof(g_run_config));
  g_run_config.is_leader = sdcard_check_leader_status();
  g_run_config.shutdown_request = false;

  /* 3. Enable HV and calibrate ADC baseline */
  printf("Enabling HV and calibrating ADC...\n");
  gpio_put(PIN_HV_ENABLE, 1);
  sleep_ms(100); /* Short settle time for HV supply */

  float baseline, rms;
  adc_calibrate(CALIBRATION_SAMPLES, &baseline, &rms);

  g_run_config.baseline = baseline;
  g_run_config.rms = rms;
  g_run_config.threshold = (int32_t)(baseline + THRESHOLD_OFFSET);
  g_run_config.reset_threshold = (int32_t)(baseline + RESET_THRESHOLD_OFFSET);

  printf("Calibration: baseline=%.1f rms=%.1f threshold=%d reset=%d\n",
         (double)baseline, (double)rms,
         (int)g_run_config.threshold,
         (int)g_run_config.reset_threshold);

  /* 4. Init inter-core queues */
  queue_init(&g_event_queue, sizeof(muon_event_t), EVENT_QUEUE_DEPTH);
  queue_init(&g_command_queue, sizeof(control_cmd_t), CMD_QUEUE_DEPTH);

  /* Init ring buffers */
  rb_init(&g_dts, g_dt_storage, DT_RING_SIZE);
  rb_init(&g_rates, g_rate_storage, RATE_RING_SIZE);

  /* 6. Launch Core 1 — MUST be before vTaskStartScheduler() */
  printf("Launching Core1 ADC detection loop...\n");
  multicore_launch_core1(core1_entry);

  /* 7. Create FreeRTOS io_task */
  g_io_params.evt_q = &g_event_queue;
  g_io_params.cmd_q = &g_command_queue;
  g_io_params.cfg = &g_run_config;
  g_io_params.stats = &g_run_stats;
  g_io_params.dts = &g_dts;
  g_io_params.rates = &g_rates;

  BaseType_t ret = xTaskCreate(
      io_task,
      "io_task",
      4096, /* Stack words */
      (void *)&g_io_params,
      configMAX_PRIORITIES - 1, /* High priority */
      NULL);

  if (ret != pdPASS) {
    printf("ERROR: xTaskCreate failed\n");
    while (true) {
      tight_loop_contents();
    }
  }

  printf("Starting FreeRTOS scheduler...\n");

  /* 8. Start FreeRTOS scheduler — this call never returns */
  vTaskStartScheduler();

  /* Should never reach here */
  printf("ERROR: vTaskStartScheduler returned\n");
  while (true) {
    tight_loop_contents();
  }

  return 0;
}
