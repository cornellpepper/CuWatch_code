#include "adc.h"
#include "gpio_pins.h"

#include "hardware/adc.h"
#include "hardware/gpio.h"
#include "pico/time.h"

#include <math.h>
#include <stdio.h>

void adc_calibrate(uint32_t n, float *baseline, float *rms)
{
  /* Init ADC hardware (safe to call multiple times) */
  adc_init();
  adc_gpio_init(PIN_SIPM_ADC);
  adc_gpio_init(PIN_TEMP_ADC);

  /* LED2 for visual feedback during calibration */
  gpio_init(PIN_LED2);
  gpio_set_dir(PIN_LED2, GPIO_OUT);
  gpio_put(PIN_LED2, 0);

  double sumval = 0.0;
  double sum_sq = 0.0;

  for (uint32_t i = 0; i < n; i++) {
    adc_select_input(ADC_CHANNEL_SIPM);
    uint16_t val = adc_read() << 4; /* Scale 12-bit→16-bit to match read_u16() */
    sumval += val;
    sum_sq += (double)val * val;

    gpio_xor_mask(1u << PIN_LED2); /* Toggle LED2 */
    sleep_ms(10);
  }

  double mean = sumval / n;
  double variance = (sum_sq / n) - (mean * mean);
  double stddev = sqrt(variance);

  *baseline = (float)mean;
  *rms = (float)stddev;

  gpio_put(PIN_LED2, 0); /* LED2 off after calibration */

  printf("ADC calibration: baseline=%.1f rms=%.1f\n", *baseline, *rms);
}

void adc_detection_loop(queue_t *evt_q, queue_t *cmd_q, run_config_t *cfg)
{
  /* Local copies of configuration — updated via command queue */
  int32_t threshold = cfg->threshold;
  int32_t reset_threshold = cfg->reset_threshold;
  bool is_leader = cfg->is_leader;

  /* Configure coincidence pin */
  gpio_init(PIN_COINCIDENCE);
  if (is_leader) {
    gpio_set_dir(PIN_COINCIDENCE, GPIO_IN);
    gpio_pull_down(PIN_COINCIDENCE);
  }
  else {
    gpio_set_dir(PIN_COINCIDENCE, GPIO_OUT);
    gpio_put(PIN_COINCIDENCE, 0);
  }

  /* LED2 is already initialized by adc_calibrate() */

  uint32_t t_last_ms = to_ms_since_boot(get_absolute_time());
  uint32_t iteration = 0;

  while (true) {
    iteration++;

    /* Poll command queue every 10,000 iterations (~few ms) */
    if (iteration % 10000 == 0) {
      control_cmd_t cmd;
      while (queue_try_remove(cmd_q, &cmd)) {
        switch (cmd.type) {
          case CMD_SET_THRESHOLD:
            threshold = cmd.value;
            cfg->threshold = cmd.value;
            break;
          case CMD_SET_RESET_THRESHOLD:
            reset_threshold = cmd.value;
            cfg->reset_threshold = cmd.value;
            break;
          case CMD_SHUTDOWN:
            cfg->shutdown_request = true;
            return; /* Exit the detection loop */
          case CMD_NEW_RUN:
            /* Signal Core0 via shutdown; Core0 will re-launch Core1 */
            return;
          case CMD_SET_LEADER:
            is_leader = (cmd.value != 0);
            cfg->is_leader = is_leader;
            gpio_set_dir(PIN_COINCIDENCE,
                         is_leader ? GPIO_IN : GPIO_OUT);
            if (is_leader) {
              gpio_pull_down(PIN_COINCIDENCE);
            }
            else {
              gpio_put(PIN_COINCIDENCE, 0);
            }
            break;
          default:
            break;
        }
      }
    }

    /* Read SiPM ADC — synchronous single conversion.
     * Scale 12-bit result to 16-bit (<<4) to match MicroPython read_u16(). */
    adc_select_input(ADC_CHANNEL_SIPM);
    uint16_t adc_val = adc_read() << 4;

    if ((int32_t)adc_val > threshold) {
      uint32_t t_now_ms = to_ms_since_boot(get_absolute_time());

      gpio_put(PIN_LED2, 1);

      uint16_t wait_counts = WAIT_COUNT_INIT;
      uint8_t coincidence = 0;

      /* Set/read coincidence pin */
      if (!is_leader) {
        gpio_put(PIN_COINCIDENCE, 1);
      }
      else {
        coincidence = gpio_get(PIN_COINCIDENCE) ? 1 : 0;
      }

      // add a small dead time -- 100 us. The peak detector time constant is like 4 ms
      busy_wait_us_32(100);

      /* Dead-time loop: wait for signal to drop below reset threshold.
       * Max WAIT_COUNT_INIT iterations (~150 µs with 1 µs waits).
       * Also latch coincidence pin during this window (leader only). */
      adc_select_input(ADC_CHANNEL_SIPM);
      while ((adc_read() << 4) > (uint16_t)reset_threshold) {
        if (is_leader && coincidence == 0) {
          coincidence = gpio_get(PIN_COINCIDENCE) ? 1 : 0;
        }
        if (wait_counts == 0) {
          break;
        }
        wait_counts--;
        busy_wait_us_32(50);
      }

      /* Sample temperature after the muon pulse has settled */
      adc_select_input(ADC_CHANNEL_TEMP);
      uint16_t temp_val = adc_read() << 4;

      gpio_put(PIN_LED2, 0);
      if (!is_leader) {
        gpio_put(PIN_COINCIDENCE, 0);
      }

      muon_event_t event = {
          .t_ms = t_now_ms,
          .dt_ms = t_now_ms - t_last_ms,
          .adc_value = adc_val,
          .temp_adc_value = temp_val,
          .wait_counts = wait_counts,
          .coincidence = coincidence,
          ._pad = 0,
      };
      t_last_ms = t_now_ms;

      /* Non-blocking push; drop event if queue full rather than block */
      queue_try_add(evt_q, &event);
    }
  }
}
