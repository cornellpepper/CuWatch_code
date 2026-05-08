#pragma once

#include "cuwatch_types.h"
#include "ring_buffer.h"
#include "pico/util/queue.h"
#include <stdbool.h>

/*
 * Mongoose-based MQTT client for CuWatch.
 * Runs on Core0 inside the FreeRTOS io_task.
 *
 * Responsibilities:
 *   - WiFi initialization (inside the Mongoose task context)
 *   - SNTP time synchronization via mg_sntp_connect()
 *   - MQTT connect to broker, subscribe to control topic
 *   - Publish muon_event_t telemetry and periodic status messages
 *   - Handle incoming JSON control commands (threshold, shutdown, leader mode)
 *   - HTTP OTA firmware upload endpoint on port 8080
 *   - Drain event_queue and write CSV via sdcard_write_event()
 *
 * This is the entry point for the FreeRTOS io_task created in main.c.
 */

typedef struct {
  queue_t *evt_q;       /* Core1 → Core0: muon events */
  queue_t *cmd_q;       /* Core0 → Core1: control commands */
  run_config_t *cfg;    /* Shared run configuration */
  run_stats_t *stats;   /* Run statistics (owned by io_task) */
  ring_buffer_t *dts;   /* Inter-event dt ring buffer for rate calc */
  ring_buffer_t *rates; /* 30-second rate snapshot ring buffer */
} io_task_params_t;

/*
 * Main loop for the FreeRTOS io_task.
 * Initializes WiFi, Mongoose, SNTP, MQTT, and HTTP OTA.
 * Runs until cfg->shutdown_request is true.
 * Called as the body of the FreeRTOS task (never returns normally).
 */
void mqtt_io_task(void *params);
