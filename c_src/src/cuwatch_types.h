#pragma once

#include <stdint.h>
#include <stdbool.h>

/*
 * Packed muon detection event sent from Core1 (ADC detection loop)
 * to Core0 (FreeRTOS io_task) via the inter-core event queue.
 *
 * Fields match the MQTT telemetry payload fields in asynchio5.py.
 */
typedef struct {
  uint32_t t_ms;           /* Monotonic time of detection (to_ms_since_boot) */
  uint32_t dt_ms;          /* Time since previous muon event (ms) */
  uint16_t adc_value;      /* SiPM ADC reading, scaled to 16-bit (raw<<4, 0..65520) */
  uint16_t temp_adc_value; /* Temperature ADC reading, scaled to 16-bit (raw<<4) */
  uint16_t wait_counts;    /* Dead-time counter remaining when signal dropped */
  uint8_t coincidence;     /* 1 if coincidence with another detector was detected */
  uint8_t _pad;            /* Alignment padding */
} muon_event_t;            /* 16 bytes total */

/* Control command types sent from Core0 (MQTT/switch) to Core1 (ADC loop) */
typedef enum {
  CMD_SET_THRESHOLD,       /* Update detection threshold */
  CMD_SET_RESET_THRESHOLD, /* Update dead-time reset threshold */
  CMD_NEW_RUN,             /* Restart data collection */
  CMD_SHUTDOWN,            /* Stop all loops cleanly */
  CMD_SET_LEADER,          /* Set leader/follower mode (value: 1=leader, 0=follower) */
} cmd_type_t;

/* Command payload pushed to command_queue */
typedef struct {
  cmd_type_t type;
  int32_t value; /* Threshold value, or 1/0 for boolean commands */
} control_cmd_t; /* 8 bytes total */

/*
 * Run configuration — shared read-only by Core1; updates flow through
 * control_cmd_t commands pushed to the command queue.
 * Volatile because Core1 reads these values directly after calibration;
 * after that, only Core0 writes (via CMD_* and command_queue).
 */
typedef struct {
  volatile int32_t threshold;       /* ADC threshold for muon detection */
  volatile int32_t reset_threshold; /* ADC level for dead-time exit */
  volatile float baseline;          /* Calibrated ADC noise floor */
  volatile float rms;               /* Calibrated baseline RMS */
  volatile bool is_leader;          /* true = reads coincidence; false = drives it */
  volatile bool shutdown_request;   /* Set to true to stop all loops */
} run_config_t;

/* Detection and rate statistics — owned and updated by Core0 io_task */
typedef struct {
  uint32_t muon_count;    /* Cumulative muon count for this run */
  uint32_t waited_count;  /* Events where dead-time counter hit zero */
  float rate_hz;          /* Current muon rate (Hz) from dt ring buffer */
  float avg_loop_time_ms; /* Average ADC sampling period (ms) */
  uint32_t start_time_ms; /* Monotonic time at run start (to_ms_since_boot) */
  int device_id;          /* Device ID read from /sd/id.txt */
} run_stats_t;

/* Calibration constants.
 * ADC values are scaled to 16-bit (adc_read()<<4) to match MicroPython
 * read_u16().  THRESHOLD_OFFSET and RESET_THRESHOLD_OFFSET are therefore
 * in 16-bit counts (0..65520). */
#define CALIBRATION_SAMPLES    500  /* ADC samples for baseline calibration */
#define THRESHOLD_OFFSET       1000 /* 16-bit counts above baseline for detection */
#define RESET_THRESHOLD_OFFSET 50   /* 16-bit counts above baseline for dead-time exit */
#define WAIT_COUNT_INIT        150  /* Max dead-time iterations (~150 µs) */

/* Ring buffer sizes */
#define DT_RING_SIZE   50  /* Inter-event times for rate calculation */
#define RATE_RING_SIZE 120 /* Rate snapshots (one per 30s = 1-hour history) */

/* Inter-core queue depths */
#define EVENT_QUEUE_DEPTH 64 /* muon_event_t entries (64 × 16B = 1KB) */
#define CMD_QUEUE_DEPTH   8  /* control_cmd_t entries */
