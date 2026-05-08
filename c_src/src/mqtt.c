#include "mqtt.h"
#include "sdcard.h"
#include "gpio_pins.h"
#include "my_secrets.h"

#include "mongoose.h"
#include "pico/cyw43_arch.h"
#include "pico/multicore.h"
#include "pico/stdlib.h"
#include "pico/time.h"
#include "pico/util/queue.h"
#include "hardware/watchdog.h"

#include "FreeRTOS.h"
#include "task.h"

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <time.h>

/* ----------------------------------------------------------------
 * Module-level state
 * ---------------------------------------------------------------- */

/* MQTT connection (NULL when disconnected) */
static struct mg_connection *s_mqtt_conn = NULL;
static bool s_mqtt_connected = false;
static bool s_sntp_synced = false;

/* OTA finalize flag: set by http_handler after sending the 200 reply.
 * The main loop calls mg_ota_end() (with Core 1 locked out) once Mongoose
 * has had a few poll cycles to flush the response to the client. */
static bool s_ota_finalize = false;

/* New-run reboot flag: set when CMD_NEW_RUN is received via MQTT.
 * Triggers a watchdog reboot after flushing the SD card, matching
 * the Python implementation's machine.reset() behaviour. */
static bool s_new_run_reboot = false;

/* Pointers to shared state — set from io_task_params_t in mqtt_io_task() */
static queue_t *s_evt_q = NULL;
static queue_t *s_cmd_q = NULL;
static run_config_t *s_cfg = NULL;
static run_stats_t *s_stats = NULL;
static ring_buffer_t *s_dts = NULL;
static ring_buffer_t *s_rates = NULL;

/* Device identification (set from run_stats_t) */
static int s_device_id = 0;
static char s_telemetry_topic[32];
static char s_status_topic[32];
static char s_control_topic[36];
static char s_client_id[16];

/* First-event flag: include run metadata on the first MQTT publish */
static bool s_first_event = true;

/* CSV file created once both MQTT is connected and NTP has synced */
static bool s_csv_initialized = false;

/* Run start timestamp (ISO8601) — set when CSV is created (after NTP sync) */
static char s_run_start_ts[32] = "";

/* Timer tracking */
static uint64_t s_last_status_ms = 0;
static uint64_t s_last_flush_ms = 0;
static uint64_t s_last_rate_ms = 0;

/* ----------------------------------------------------------------
 * Timestamp helpers (uses Mongoose's mg_now() — epoch ms after SNTP sync)
 * ---------------------------------------------------------------- */

static void get_iso8601_timestamp(char *buf, size_t len)
{
  uint64_t now_ms = mg_now(); /* Epoch milliseconds (set by SNTP) */
  if (now_ms < 1000000000000ULL) {
    /* SNTP not yet synced — emit boot-relative placeholder */
    snprintf(buf, len, "1970-01-01T00:00:00.000000Z");
    return;
  }
  time_t now_sec = (time_t)(now_ms / 1000);
  struct tm t;
  gmtime_r(&now_sec, &t);
  strftime(buf, len, "%Y-%m-%dT%H:%M:%S.000000Z", &t);
}

/* ----------------------------------------------------------------
 * JSON telemetry builder
 * ---------------------------------------------------------------- */

static int build_telemetry_json(char *buf, size_t buf_size,
                                const muon_event_t *ev)
{
  char ts[32];
  get_iso8601_timestamp(ts, sizeof(ts));

  int n = snprintf(buf, buf_size,
                   "{\"device_number\":%d,\"muon_count\":%u,"
                   "\"adc_v\":%u,\"temp_adc_v\":%u,"
                   "\"dt\":%u,\"ts\":\"%s\","
                   "\"t_ms\":%u,\"wait_cnt\":%u,\"coincidence\":%u",
                   s_device_id,
                   (unsigned)s_stats->muon_count,
                   (unsigned)ev->adc_value,
                   (unsigned)ev->temp_adc_value,
                   (unsigned)ev->dt_ms,
                   ts,
                   (unsigned)ev->t_ms,
                   (unsigned)ev->wait_counts,
                   (unsigned)ev->coincidence);

  if (s_first_event && n < (int)buf_size - 1) {
    /* Append first-event run metadata.
     * s_run_start_ts is set in try_init_csv() once NTP has synced; if the
     * first event fires before NTP sync (MQTT connected first), fall back to
     * get_iso8601_timestamp() so the field is never an empty string. */
    char run_start[32];
    if (s_run_start_ts[0] != '\0') {
      memcpy(run_start, s_run_start_ts, sizeof(run_start));
    } else {
      get_iso8601_timestamp(run_start, sizeof(run_start));
    }
    n += snprintf(buf + n, buf_size - (size_t)n,
                  ",\"run_start\":\"%s\","
                  "\"baseline\":%d,"
                  "\"reset_threshold\":%d,"
                  "\"threshold\":%d,"
                  "\"is_leader\":%s",
                  run_start,
                  (int)s_cfg->baseline,
                  (int)s_cfg->reset_threshold,
                  (int)s_cfg->threshold,
                  s_cfg->is_leader ? "true" : "false");
    s_first_event = false;
  }

  if (n < (int)buf_size - 2) {
    buf[n++] = '}';
    buf[n] = '\0';
  }
  return n;
}

static void build_status_json(char *buf, size_t buf_size)
{
  uint32_t runtime_ms = (uint32_t)(to_ms_since_boot(get_absolute_time()) - s_stats->start_time_ms);
  snprintf(buf, buf_size,
           "{\"rate\":%.2f,\"muon_count\":%u,"
           "\"threshold\":%d,\"reset_threshold\":%d,"
           "\"baseline\":%.1f,\"runtime\":%.1f,"
           "\"is_leader\":%s,\"avg_time_ms\":%.3f}",
           (double)s_stats->rate_hz,
           (unsigned)s_stats->muon_count,
           (int)s_cfg->threshold,
           (int)s_cfg->reset_threshold,
           (double)s_cfg->baseline,
           (double)runtime_ms / 1000.0,
           s_cfg->is_leader ? "true" : "false",
           (double)s_stats->avg_loop_time_ms);
}

/* ----------------------------------------------------------------
 * Control message parsing
 * ---------------------------------------------------------------- */

static void handle_control_message(const char *data, size_t len)
{
  /* Parse threshold */
  double threshold_val;
  if (mg_json_get_num(mg_str_n(data, len), "$.threshold", &threshold_val)) {
    int32_t new_thresh = (int32_t)threshold_val;
    s_cfg->threshold = new_thresh;
    control_cmd_t cmd = {.type = CMD_SET_THRESHOLD, .value = new_thresh};
    queue_try_add(s_cmd_q, &cmd);
    printf("Threshold updated via MQTT: %d\n", (int)new_thresh);
  }

  /* Parse reset_threshold */
  double reset_val;
  if (mg_json_get_num(mg_str_n(data, len), "$.reset_threshold", &reset_val)) {
    int32_t new_reset = (int32_t)reset_val;
    s_cfg->reset_threshold = new_reset;
    control_cmd_t cmd = {.type = CMD_SET_RESET_THRESHOLD, .value = new_reset};
    queue_try_add(s_cmd_q, &cmd);
    printf("Reset threshold updated via MQTT: %d\n", (int)new_reset);
  }

  /* Parse new_run */
  bool new_run_val = false;
  if (mg_json_get_bool(mg_str_n(data, len), "$.new_run", &new_run_val) && new_run_val) {
    printf("Received new_run via MQTT — will reboot after SD flush\n");
    control_cmd_t cmd = {.type = CMD_NEW_RUN, .value = 0};
    queue_try_add(s_cmd_q, &cmd);
    s_new_run_reboot = true; /* Signal main loop to reboot (matches Python machine.reset()) */
  }

  /* Parse shutdown */
  bool shutdown_val = false;
  if (mg_json_get_bool(mg_str_n(data, len), "$.shutdown", &shutdown_val) && shutdown_val) {
    printf("Received shutdown via MQTT\n");
    s_cfg->shutdown_request = true;
    control_cmd_t cmd = {.type = CMD_SHUTDOWN, .value = 0};
    queue_try_add(s_cmd_q, &cmd);
  }

  /* Parse make_leader */
  bool leader_bool = false;
  double leader_val = 0.0;
  bool has_make_leader = mg_json_get_bool(mg_str_n(data, len), "$.make_leader", &leader_bool) || mg_json_get_num(mg_str_n(data, len), "$.make_leader", &leader_val);
  if (has_make_leader) {
    bool make_leader = leader_bool || (leader_val != 0.0);
    control_cmd_t cmd = {.type = CMD_SET_LEADER, .value = make_leader ? 1 : 0};
    queue_try_add(s_cmd_q, &cmd);
    if (make_leader) {
      sdcard_make_leader();
    }
    else {
      sdcard_make_follower();
    }
    printf("Leader mode %s via MQTT\n", make_leader ? "enabled" : "disabled");
  }
}

/* ----------------------------------------------------------------
 * HTTP handler — OTA firmware upload
 *
 * This version of Mongoose lacks HTTP chunk streaming events, so OTA
 * uses the multi-POST pattern: the client (ota_upload.py) splits the
 * binary into 4 KB chunks and POSTs each one separately.
 *
 * Protocol:
 *   POST /ota?offset=0&total=<size>       — first chunk (calls mg_ota_begin)
 *   POST /ota?offset=4096&total=<size>    — subsequent chunks
 *   POST /ota?offset=<size>&total=<size>  — empty body  (calls mg_ota_end)
 *
 * Upload with the provided helper script:
 *   python3 c_src/ota_upload.py <pico-ip> cuwatch.bin
 *
 * NOTE: use cuwatch.bin (raw binary), NOT cuwatch.uf2.
 * ---------------------------------------------------------------- */

static void http_handler(struct mg_connection *c, int ev, void *ev_data)
{
  if (ev == MG_EV_HTTP_MSG) {
    struct mg_http_message *hm = (struct mg_http_message *)ev_data;

    if (mg_match(hm->uri, mg_str("/ota"), NULL)) {
      char offset_str[20] = "", total_str[20] = "";
      long ofs = -1, tot = -1;

      mg_http_get_var(&hm->query, "offset", offset_str, sizeof(offset_str));
      mg_http_get_var(&hm->query, "total", total_str, sizeof(total_str));
      if (offset_str[0] != '\0') {
        ofs = atol(offset_str);
      }
      if (total_str[0] != '\0') {
        tot = atol(total_str);
      }

      if (ofs < 0 || tot < 0) {
        mg_http_reply(c, 400, "", "offset and total params required\n");
      }
      else if (ofs == 0 && !mg_ota_begin((size_t)tot)) {
        mg_http_reply(c, 500, "", "mg_ota_begin(%ld) failed\n", tot);
      }
      else if (hm->body.len > 0) {
        /* Pause Core 1 before erasing/programming flash.
         * flash_range_erase/program cannot run while any core fetches
         * instructions from XIP flash; Core 1 must have called
         * multicore_lockout_victim_init() at startup to respond here. */
        multicore_lockout_start_blocking();
        bool write_ok = mg_ota_write(hm->body.buf, hm->body.len);
        multicore_lockout_end_blocking();
        if (!write_ok) {
          mg_http_reply(c, 500, "", "mg_ota_write failed at offset %ld\n", ofs);
          mg_ota_end();
        }
        else {
          mg_http_reply(c, 200, "", "ok\n");
        }
      }
      else {
        /* body.len == 0: all chunks received.
         * Send the HTTP reply NOW, before the partition swap.
         * mg_ota_end() erases/programs up to 2 MB of flash and then
         * reboots — it would destroy the TCP connection before this
         * reply could ever be flushed.  The main event loop handles
         * the actual mg_ota_end() call once the response is on the wire. */
        MG_INFO(("OTA upload complete — scheduling partition swap"));
        mg_http_reply(c, 200, "", "ok\n");
        s_ota_finalize = true;
      }
    }
    else if (mg_match(hm->uri, mg_str("/status"), NULL)) {
      char json[512];
      build_status_json(json, sizeof(json));
      mg_http_reply(c, 200, "Content-Type: application/json\r\n", "%s\n", json);
    }
    else {
      mg_http_reply(c, 404, "", "Not found\n");
    }
  }
}

/* ----------------------------------------------------------------
 * CSV initialization (deferred until both MQTT connected and NTP synced)
 * ---------------------------------------------------------------- */

/* Create the CSV file once both conditions are satisfied.
 * Called from two trigger points — whichever fires second creates the file:
 *   1. MG_EV_MQTT_OPEN  (only if NTP already synced)
 *   2. sntp_user_cb MG_EV_SNTP_TIME  (only if MQTT already connected)
 * 'force' skips the NTP check — used as a 2-minute fallback when NTP
 * never responds, so data is at least captured with a wrong timestamp. */
static void try_init_csv(bool force)
{
  if (s_csv_initialized || !s_mqtt_connected) {
    return;
  }
  uint64_t now_ms = mg_now();
  if (now_ms < 1000000000000ULL && !force) {
    return; /* NTP not synced yet — wait */
  }

  /* Capture run start timestamp now that we have a real (or fallback) time */
  get_iso8601_timestamp(s_run_start_ts, sizeof(s_run_start_ts));
  uint32_t epoch_sec = (uint32_t)(now_ms / 1000);

  if (sdcard_init_csv_file(s_cfg->baseline, s_cfg->rms,
                           s_cfg->threshold, s_cfg->reset_threshold,
                           s_run_start_ts, s_cfg->is_leader,
                           epoch_sec)) {
    s_csv_initialized = true;
    printf("CSV file created at epoch %u  ts=%s\n",
           (unsigned)epoch_sec, s_run_start_ts);
  }
  else {
    printf("WARNING: CSV file creation failed\n");
  }
}

/* ----------------------------------------------------------------
 * MQTT event handler
 * ---------------------------------------------------------------- */

static void mqtt_handler(struct mg_connection *c, int ev, void *ev_data)
{
  if (ev == MG_EV_CONNECT) {
    /* TCP connected — Mongoose sends MQTT CONNECT automatically
     * using the opts passed to mg_mqtt_connect() in the timer. */
    MG_INFO(("MQTT TCP connected"));
  }
  else if (ev == MG_EV_MQTT_OPEN) {
    /* CONNACK received — subscribe to control topic */
    struct mg_mqtt_opts sub_opts = {
        .topic = mg_str(s_control_topic),
        .qos = 0,
    };
    mg_mqtt_sub(c, &sub_opts);
    s_mqtt_connected = true;
    MG_INFO(("MQTT connected, subscribed to %s", s_control_topic));

    /* Try to create CSV now — succeeds only if NTP has already synced.
     * If not yet synced, try_init_csv() will be called again from
     * sntp_user_cb once MG_EV_SNTP_TIME fires. */
    try_init_csv(false);
  }
  else if (ev == MG_EV_MQTT_MSG) {
    struct mg_mqtt_message *msg = (struct mg_mqtt_message *)ev_data;
    handle_control_message(msg->data.buf, msg->data.len);
  }
  else if (ev == MG_EV_ERROR) {
    MG_ERROR(("MQTT error: %s", (char *)ev_data));
  }
  else if (ev == MG_EV_CLOSE) {
    MG_INFO(("MQTT connection closed"));
    s_mqtt_connected = false;
    s_mqtt_conn = NULL; /* Trigger reconnect in timer */
  }
}

/* ----------------------------------------------------------------
 * Mongoose timers
 * ---------------------------------------------------------------- */

/* Reconnect timer: runs every 3 seconds to re-establish MQTT if disconnected */
static void timer_mqtt_reconnect(void *arg)
{
  struct mg_mgr *mgr = (struct mg_mgr *)arg;
  if (s_mqtt_conn == NULL) {
    char url[64];
    snprintf(url, sizeof(url), "mqtt://%s:%d", MQTT_BROKER, MQTT_PORT);
    MG_INFO(("Connecting to MQTT broker: %s", url));
    /* Pass MQTT CONNECT options here; Mongoose sends them on TCP connect */
    struct mg_mqtt_opts opts = {
        .client_id = mg_str(s_client_id),
        .keepalive = 60,
        .version = 4,
        .clean = true,
    };
    s_mqtt_conn = mg_mqtt_connect(mgr, url, &opts, mqtt_handler, NULL);
  }
  else if (s_mqtt_connected) {
    mg_mqtt_ping(s_mqtt_conn);
  }
}

/* SNTP event callback — called by Mongoose when the NTP response arrives
 * (MG_EV_SNTP_TIME) or when the connection closes (MG_EV_CLOSE) without a
 * response (3-second internal timeout inside sntp_cb). */
static void sntp_user_cb(struct mg_connection *c, int ev, void *ev_data)
{
  if (ev == MG_EV_SNTP_TIME) {
    uint64_t *epoch_ms = (uint64_t *)ev_data;
    uint32_t epoch_sec = (uint32_t)(*epoch_ms / 1000);
    /* epoch_sec in human terms: 2025 ≈ 1735689600 */
    printf("SNTP: sync OK  epoch_ms=%llu  epoch_sec=%lu\n",
           (unsigned long long)*epoch_ms, (unsigned long)epoch_sec);
    s_sntp_synced = true;

    /* If MQTT was already connected before NTP synced, create the CSV now
     * that we have a real timestamp for the filename and header. */
    try_init_csv(false);
  }
  else if (ev == MG_EV_ERROR) {
    printf("SNTP: error: %s  (will retry)\n", (char *)ev_data);
  }
  else if (ev == MG_EV_CLOSE) {
    uint64_t t = mg_now();
    if (t < 1000000000000ULL) {
      /* Closed without receiving a valid time (timeout or DNS failure) */
      printf("SNTP: connection closed without sync  mg_now=%llu  (will retry)\n",
             (unsigned long long)t);
    }
  }
  (void)c;
}

/* SNTP timer: attempt NTP sync every 10 seconds until successful,
 * then re-sync every hour. The internal sntp_cb times out after 3 s,
 * so 10 s gives it room to fail and retry without creating a backlog. */
static void timer_sntp(void *arg)
{
  struct mg_mgr *mgr = (struct mg_mgr *)arg;
  uint64_t t = mg_now();
  if (!s_sntp_synced || t < 1000000000000ULL) {
    char sntp_url[48];
    snprintf(sntp_url, sizeof(sntp_url), "udp://%s:123", NTP_SERVER);
    printf("SNTP: attempting sync with %s  (mg_now=%llu)\n",
           NTP_SERVER, (unsigned long long)t);
    mg_sntp_connect(mgr, sntp_url, sntp_user_cb, NULL);
    /* s_sntp_synced is set to true only in sntp_user_cb on MG_EV_SNTP_TIME */
  }
}

/* ----------------------------------------------------------------
 * Publish helpers
 * ---------------------------------------------------------------- */

static void publish_telemetry(const muon_event_t *ev)
{
  if (!s_mqtt_connected || s_mqtt_conn == NULL) {
    return;
  }

  char buf[512];
  int n = build_telemetry_json(buf, sizeof(buf), ev);

  struct mg_mqtt_opts pub_opts = {
      .topic = mg_str(s_telemetry_topic),
      .message = mg_str_n(buf, (size_t)n),
      .qos = 0,
  };
  mg_mqtt_pub(s_mqtt_conn, &pub_opts);
}

static void publish_status(void)
{
  if (!s_mqtt_connected || s_mqtt_conn == NULL) {
    return;
  }

  char buf[512];
  build_status_json(buf, sizeof(buf));

  struct mg_mqtt_opts pub_opts = {
      .topic = mg_str(s_status_topic),
      .message = mg_str(buf),
      .qos = 0,
  };
  mg_mqtt_pub(s_mqtt_conn, &pub_opts);
  MG_INFO(("Status published: rate=%.2f Hz, count=%u",
           (double)s_stats->rate_hz, (unsigned)s_stats->muon_count));
}

/* ----------------------------------------------------------------
 * Main io_task — FreeRTOS task body
 * ---------------------------------------------------------------- */

void mqtt_io_task(void *params)
{
  io_task_params_t *p = (io_task_params_t *)params;
  s_evt_q = p->evt_q;
  s_cmd_q = p->cmd_q;
  s_cfg = p->cfg;
  s_stats = p->stats;
  s_dts = p->dts;
  s_rates = p->rates;
  s_device_id = s_stats->device_id;

  /* Build MQTT topic strings from device ID */
  snprintf(s_client_id, sizeof(s_client_id), "cuwatch_%03d", s_device_id);
  snprintf(s_telemetry_topic, sizeof(s_telemetry_topic), "telemetry/%03d", s_device_id);
  snprintf(s_status_topic, sizeof(s_status_topic), "status/%03d", s_device_id);
  snprintf(s_control_topic, sizeof(s_control_topic), "control/%03d/set", s_device_id);

  printf("Device ID: %d  client_id: %s  telemetry: %s  control: %s\n",
         s_device_id, s_client_id, s_telemetry_topic, s_control_topic);

  if (s_device_id == 0) {
    printf("WARNING: device ID is 0 — check that id.txt exists on the SD card\n");
  }

  /* ---- WiFi initialization (must be inside FreeRTOS task context) ---- */
  printf("Initializing WiFi...\n");
  if (cyw43_arch_init() != 0) {
    printf("cyw43_arch_init failed\n");
    vTaskDelete(NULL);
    return;
  }
  cyw43_arch_enable_sta_mode();

  /* LED feedback during WiFi connection attempt */
  printf("Connecting to WiFi SSID: %s\n", WIFI_SSID);
  bool wifi_ok = false;
  for (int attempt = 0; attempt < 3 && !wifi_ok; attempt++) {
    int result = cyw43_arch_wifi_connect_timeout_ms(
        WIFI_SSID,
        WIFI_PASSWORD,
        WIFI_PASSWORD ? CYW43_AUTH_WPA2_AES_PSK : CYW43_AUTH_OPEN,
        30000);
    if (result == 0) {
      wifi_ok = true;
    }
    else {
      printf("WiFi attempt %d failed (%d), retrying...\n", attempt + 1, result);
      sleep_ms(2000);
    }
  }
  if (!wifi_ok) {
    printf("WiFi connection failed after 3 attempts\n");
    /* Continue without WiFi — still log to SD card */
  }
  else {
    printf("WiFi connected\n");
    cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, 1); /* Solid LED = connected */
  }

  /* ---- Mongoose event manager ---- */
  struct mg_mgr mgr;
  mg_mgr_init(&mgr);
  mg_log_set(MG_LL_INFO);

  /* ---- Timers ---- */
  /* SNTP: attempt every 10 s until synced, then every hour */
  mg_timer_add(&mgr, 10000, MG_TIMER_REPEAT | MG_TIMER_RUN_NOW, timer_sntp, &mgr);

  /* MQTT reconnect: check every 3 seconds */
  mg_timer_add(&mgr, 3000, MG_TIMER_REPEAT | MG_TIMER_RUN_NOW, timer_mqtt_reconnect, &mgr);

  /* ---- HTTP OTA listener on port 8080 ---- */
  mg_http_listen(&mgr, "http://0.0.0.0:8080", http_handler, NULL);
  printf("OTA HTTP server listening on port 8080\n");
  printf("  python3 c_src/ota_upload.py <IP> cuwatch.bin\n");

  /* ---- Main event loop ---- */
  s_stats->start_time_ms = to_ms_since_boot(get_absolute_time());
  uint64_t now_ms;

  while (!s_cfg->shutdown_request) {
    /* Drive Mongoose networking (MQTT + HTTP + SNTP) */
    mg_mgr_poll(&mgr, 10);

    /* OTA finalize: http_handler set this flag after sending the 200 reply.
     * Poll a few more times so Mongoose can flush the response to the TCP
     * socket, then lock out Core 1 (XIP hazard) and call mg_ota_end().
     * mg_ota_end() swaps the flash partitions (~2 MB) and reboots the device;
     * multicore_lockout_end_blocking() is only reached if it fails. */
    if (s_ota_finalize) {
      s_ota_finalize = false;
      for (int i = 0; i < 5; i++) {
        mg_mgr_poll(&mgr, 20);
      }
      MG_INFO(("OTA: locking Core 1 for partition swap"));
      multicore_lockout_start_blocking();
      if (!mg_ota_end()) {
        multicore_lockout_end_blocking();
        printf("OTA: mg_ota_end failed — continuing with old firmware\n");
      }
      /* Device reboots inside mg_ota_end() on success; not reached. */
    }

    now_ms = to_ms_since_boot(get_absolute_time());

    /* Drain event queue — process all pending muon events */
    muon_event_t event;
    while (queue_try_remove(s_evt_q, &event)) {
      s_stats->muon_count++;
      if (event.wait_counts == 0) {
        s_stats->waited_count++; /* Dead-time counter hit zero before signal dropped */
      }

      /* Update inter-event time ring buffer and rate */
      rb_push(s_dts, (float)event.dt_ms);
      float avg_dt = rb_average(s_dts);
      s_stats->rate_hz = (avg_dt > 0.0f) ? (1000.0f / avg_dt) : 0.0f;

      /* Publish MQTT telemetry */
      publish_telemetry(&event);

      /* Write CSV row to SD card */
      sdcard_write_event(&event, s_stats->muon_count);
    }

    /* Update rate snapshot ring buffer every 30 seconds */
    if (now_ms - s_last_rate_ms >= 30000) {
      rb_push(s_rates, s_stats->rate_hz);
      s_last_rate_ms = now_ms;
    }

    /* Publish MQTT status every 30 seconds */
    if (now_ms - s_last_status_ms >= 30000) {
      publish_status();
      s_last_status_ms = now_ms;
    }

    /* Flush SD card every 60 seconds */
    if (now_ms - s_last_flush_ms >= 60000) {
      sdcard_flush();
      s_last_flush_ms = now_ms;
    }

    /* CSV fallback: if NTP never synced after 30 s and MQTT is up, create
     * the CSV with a 1970-epoch filename.  At detector rates of several Hz,
     * waiting longer loses too many events from the SD card log. */
    if (!s_csv_initialized &&
        (now_ms - s_stats->start_time_ms > 30000)) {
      printf("NTP not synced after 30 s — creating CSV with epoch 0\n");
      try_init_csv(true); /* force=true: skip NTP check */
    }

    /* New-run reboot: CMD_NEW_RUN was received via MQTT.  Flush and close SD,
     * then reboot via watchdog — equivalent to Python's machine.reset().
     * Give Core 1 a moment to drain its current event (it will stop on its
     * own after receiving CMD_NEW_RUN), then reboot cleanly. */
    if (s_new_run_reboot) {
      printf("new_run: flushing SD and rebooting...\n");
      sdcard_flush();
      sdcard_unmount();
      mg_mgr_free(&mgr);
      cyw43_arch_deinit();
      watchdog_reboot(0, 0, 100); /* 100 ms delay then reset */
      while (true) {
        tight_loop_contents();
      }
    }
  }

  /* ---- Shutdown sequence ---- */
  printf("mqtt_io_task: shutdown requested\n");
  sdcard_flush();
  sdcard_unmount();
  mg_mgr_free(&mgr);
  cyw43_arch_deinit();

  vTaskDelete(NULL);
}
