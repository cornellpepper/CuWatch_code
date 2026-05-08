#pragma once

#include "cuwatch_types.h"
#include "pico/util/queue.h"

/*
 * ADC calibration and muon detection loop.
 * Runs on Core1 (bare-metal, no FreeRTOS).
 *
 * Detection algorithm (ported from src/asynchio5.py):
 *   1. Sample ADC0 (SiPM) continuously
 *   2. If reading > threshold → muon event
 *   3. Dead-time: poll ADC0 until < reset_threshold (max WAIT_COUNT_INIT iters)
 *   4. Sample ADC1 (temperature) after dead-time
 *   5. Coincidence: follower drives PIN_COINCIDENCE HIGH; leader reads it
 *   6. Push muon_event_t to event_queue (non-blocking)
 *   7. Poll command_queue every 10,000 iterations for threshold/mode updates
 */

/*
 * Calibrate ADC baseline by averaging n samples with 10ms between each.
 * LED2 toggles during calibration for visual feedback.
 * Must be called from Core0 before launching Core1.
 *
 * @param n        Number of samples (500 recommended)
 * @param baseline Output: mean ADC value
 * @param rms      Output: standard deviation of samples
 */
void adc_calibrate(uint32_t n, float *baseline, float *rms);

/*
 * Core1 entry point: tight ADC sampling and muon detection loop.
 * Runs until a CMD_SHUTDOWN command is received via cmd_q.
 *
 * @param evt_q  Queue to push muon_event_t events to (to Core0)
 * @param cmd_q  Queue to pop control_cmd_t commands from (from Core0)
 * @param cfg    Run configuration (read threshold/is_leader; shutdown via cmd_q)
 */
void adc_detection_loop(queue_t *evt_q, queue_t *cmd_q, run_config_t *cfg);
