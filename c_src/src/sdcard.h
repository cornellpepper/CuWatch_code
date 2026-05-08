#pragma once

#include "cuwatch_types.h"
#include <stdbool.h>
#include <stdint.h>

/*
 * SD card interface using no-OS-FatFS-SD-SDIO-SPI-RPi-Pico.
 * Implements the required hw_config functions and provides CSV logging.
 *
 * All functions must be called from Core0 (FreeRTOS io_task) only.
 * FatFS is NOT thread-safe; concurrent access from Core1 is not supported.
 */

/* Mount the SD card at "/sd".
 * Returns true on success. Must be called before any other sdcard_ function. */
bool sdcard_mount(void);

/* Unmount the SD card safely (sync + f_mount NULL).
 * Call before power-off or when done with the SD card. */
void sdcard_unmount(void);

/* Read the integer device ID from /sd/id.txt.
 * Returns 0 if the file is missing or unreadable. */
int sdcard_read_device_id(void);

/* Check whether this node is the leader.
 * Returns true (leader) if is_secondary does NOT exist.
 * Returns false (follower) if is_secondary exists. */
bool sdcard_check_leader_status(void);

/* Create a new CSV data file with the standard 3-row header.
 * Filename: /sd/muon_data_YYYYMMDD_HHMM.csv
 * The epoch_sec parameter is Unix time used to generate the filename timestamp.
 * Returns true on success. */
bool sdcard_init_csv_file(float baseline, float rms,
                          int32_t threshold, int32_t reset_threshold,
                          const char *run_start_ts, bool is_leader,
                          uint32_t epoch_sec);

/* Write one CSV data row for a detected muon event.
 * muon_count is the cumulative count for the current run. */
void sdcard_write_event(const muon_event_t *ev, uint32_t muon_count);

/* Flush the CSV file to SD card (f_sync).
 * Call periodically (e.g., every 60 seconds) and on shutdown. */
void sdcard_flush(void);

/* Write the is_secondary marker file (make this node a follower). */
void sdcard_make_follower(void);

/* Remove the is_secondary marker file (make this node a leader). */
void sdcard_make_leader(void);
