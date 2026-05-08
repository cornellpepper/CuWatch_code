#include "sdcard.h"
#include "gpio_pins.h"

/* no-OS-FatFS-SD-SDIO-SPI-RPi-Pico headers */
#include "hw_config.h"
#include "ff.h"
#include "f_util.h"
#include "sd_card.h"

#include "hardware/spi.h"
#include "pico/stdlib.h"

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

/* ----------------------------------------------------------------
 * Hardware configuration — required by no-OS-FatFS-SD-SDIO-SPI-RPi-Pico.
 * Implements sd_get_num() and sd_get_by_num() to describe the SPI SD card
 * wiring on the Pepper V2 baseboard.
 * ---------------------------------------------------------------- */

static spi_t g_spi = {
    .hw_inst = spi0,
    .miso_gpio = PIN_SPI0_RX, /* GPIO 0 */
    .mosi_gpio = PIN_SPI0_TX, /* GPIO 3 */
    .sck_gpio = PIN_SPI0_SCK, /* GPIO 2 */
    .baud_rate = 12500000,    /* 12.5 MHz */
};

static sd_spi_if_t g_spi_if = {
    .spi = &g_spi,
    .ss_gpio = PIN_SPI0_CS, /* GPIO 1 */
};

static sd_card_t g_sd_card = {
    .type = SD_IF_SPI,
    .spi_if_p = &g_spi_if,
};

/* Required by no-OS-FatFS library */
size_t sd_get_num(void)
{
  return 1;
}

sd_card_t *sd_get_by_num(size_t num)
{
  if (num == 0)
    return &g_sd_card;
  return NULL;
}

/* ----------------------------------------------------------------
 * FatFS state
 * ---------------------------------------------------------------- */

static FATFS g_fatfs;
static FIL g_csv_file;
static bool g_csv_open = false;
static bool g_sd_mounted = false;

/* ----------------------------------------------------------------
 * Mount / unmount
 * ---------------------------------------------------------------- */

bool sdcard_mount(void)
{
  /* Mount to logical drive "" (drive 0, the only drive).
   * The no-OS-FatFS library has FF_STR_VOLUME_ID=0, so FatFS only accepts
   * numeric drive IDs — string labels like "/sd/" are NOT supported.
   * Using "/sd/" as the mount path would cause f_open to look for a
   * subdirectory named "sd" on the volume and return FR_NO_PATH (5).
   * All file paths must be bare names relative to the card root (e.g.
   * "id.txt"), not prefixed with "/sd/". */
  FRESULT fr = f_mount(&g_fatfs, "", 1);
  if (fr != FR_OK) {
    printf("sdcard_mount: f_mount failed (%d)\n", (int)fr);
    return false;
  }
  g_sd_mounted = true;
  printf("SD card mounted\n");
  return true;
}

void sdcard_unmount(void)
{
  if (g_csv_open) {
    f_sync(&g_csv_file);
    f_close(&g_csv_file);
    g_csv_open = false;
  }
  f_mount(NULL, "", 0);
  g_sd_mounted = false;
  printf("SD card unmounted\n");
}

/* ----------------------------------------------------------------
 * Configuration file reads
 * ---------------------------------------------------------------- */

int sdcard_read_device_id(void)
{
  if (!g_sd_mounted)
    return 0;

  FIL f;
  UINT br;
  char buf[16];

  FRESULT fr = f_open(&f, "id.txt", FA_READ);
  if (fr != FR_OK) {
    printf("sdcard_read_device_id: cannot open id.txt (%d)\n", (int)fr);
    return 0;
  }
  fr = f_read(&f, buf, sizeof(buf) - 1, &br);
  f_close(&f);
  if (fr != FR_OK || br == 0)
    return 0;

  buf[br] = '\0';
  int id = atoi(buf);
  printf("Device ID: %d\n", id);
  return id;
}

bool sdcard_check_leader_status(void)
{
  if (!g_sd_mounted)
    return true; /* Default to leader if SD unavailable */

  FILINFO fi;
  FRESULT fr = f_stat("is_secondary", &fi);
  bool is_leader = (fr != FR_OK); /* Leader if file does NOT exist */
  printf("Node is %s\n", is_leader ? "leader" : "follower");
  return is_leader;
}

/* ----------------------------------------------------------------
 * CSV file management
 * ---------------------------------------------------------------- */

/* Decompose Unix epoch seconds into date/time components for filename */
static void epoch_to_datetime(uint32_t epoch,
                              int *year, int *month, int *day,
                              int *hour, int *min)
{
  /* Simple, portable Unix epoch → calendar conversion */
  uint32_t secs = epoch % 60;
  (void)secs;
  uint32_t days = epoch / 86400;
  uint32_t rem = epoch % 86400;
  *hour = (int)(rem / 3600);
  *min = (int)((rem % 3600) / 60);

  /* Days since 1970-01-01 → calendar date */
  int y = 1970;
  while (true) {
    bool leap = ((y % 4 == 0 && y % 100 != 0) || (y % 400 == 0));
    uint32_t ydays = leap ? 366 : 365;
    if (days < ydays)
      break;
    days -= ydays;
    y++;
  }
  *year = y;

  static const int mdays[12] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  bool leap = ((*year % 4 == 0 && *year % 100 != 0) || (*year % 400 == 0));
  int m = 1;
  for (m = 1; m <= 12; m++) {
    int md = mdays[m - 1] + (m == 2 && leap ? 1 : 0);
    if ((int)days < md)
      break;
    days -= (uint32_t)md;
  }
  *month = m;
  *day = (int)days + 1;
}

bool sdcard_init_csv_file(float baseline, float rms,
                          int32_t threshold, int32_t reset_threshold,
                          const char *run_start_ts, bool is_leader,
                          uint32_t epoch_sec)
{
  if (!g_sd_mounted)
    return false;

  if (g_csv_open) {
    f_sync(&g_csv_file);
    f_close(&g_csv_file);
    g_csv_open = false;
  }

  /* Build filename from epoch time */
  int year, month, day, hour, min;
  epoch_to_datetime(epoch_sec, &year, &month, &day, &hour, &min);

  char path[48];
  snprintf(path, sizeof(path), "muon_data_%04d%02d%02d_%02d%02d.csv",
           year, month, day, hour, min);

  FRESULT fr = f_open(&g_csv_file, path, FA_WRITE | FA_CREATE_ALWAYS);
  if (fr != FR_OK) {
    printf("sdcard_init_csv_file: f_open(%s) failed (%d)\n", path, (int)fr);
    return false;
  }

  /* 3-row header matching Python asynchio5.py format exactly */
  char header[256];
  UINT written;
  int n;

  /* Row 1: field names */
  n = snprintf(header, sizeof(header),
               "baseline,stddev,threshold,reset_threshold,run_start_time,is_leader\n");
  f_write(&g_csv_file, header, (UINT)n, &written);

  /* Row 2: calibration values */
  n = snprintf(header, sizeof(header),
               "%.1f, %.1f, %d, %d, %s, %d\n",
               (double)baseline, (double)rms,
               (int)threshold, (int)reset_threshold,
               run_start_ts ? run_start_ts : "unknown",
               is_leader ? 1 : 0);
  f_write(&g_csv_file, header, (UINT)n, &written);

  /* Row 3: column headers */
  n = snprintf(header, sizeof(header),
               "Muon Count,ADC,temperature_ADC,dt,t,t_wait,coinc\n");
  f_write(&g_csv_file, header, (UINT)n, &written);

  g_csv_open = true;
  printf("CSV file opened: %s\n", path);
  return true;
}

void sdcard_write_event(const muon_event_t *ev, uint32_t muon_count)
{
  if (!g_csv_open)
    return;

  char line[80];
  int n = snprintf(line, sizeof(line),
                   "%u, %u, %u, %u, %u, %u, %u\n",
                   (unsigned)muon_count,
                   (unsigned)ev->adc_value,
                   (unsigned)ev->temp_adc_value,
                   (unsigned)ev->dt_ms,
                   (unsigned)ev->t_ms,
                   (unsigned)ev->wait_counts,
                   (unsigned)ev->coincidence);

  UINT written;
  f_write(&g_csv_file, line, (UINT)n, &written);
}

void sdcard_flush(void)
{
  if (g_csv_open) {
    f_sync(&g_csv_file);
  }
}

/* ----------------------------------------------------------------
 * Leader / follower marker
 * ---------------------------------------------------------------- */

void sdcard_make_follower(void)
{
  if (!g_sd_mounted)
    return;

  FILINFO fi;
  if (f_stat("is_secondary", &fi) == FR_OK) {
    printf("is_secondary already exists\n");
    return;
  }
  FIL f;
  FRESULT fr = f_open(&f, "is_secondary", FA_WRITE | FA_CREATE_ALWAYS);
  if (fr == FR_OK) {
    UINT written;
    f_write(&f, "This node is a follower", 23, &written);
    f_close(&f);
    printf("Created is_secondary\n");
  }
}

void sdcard_make_leader(void)
{
  if (!g_sd_mounted)
    return;

  FRESULT fr = f_unlink("is_secondary");
  if (fr == FR_OK) {
    printf("Removed is_secondary\n");
  }
  else {
    printf("is_secondary does not exist\n");
  }
}
