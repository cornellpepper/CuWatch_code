"""MQTT client version of the code, where the Pico-W is an MQTT client and sends 
the data to an MQTT broker running on a remote server based on the raspberry Pi."""

from machine import ADC, Pin, RTC
import asyncio
import machine
import sdcard
import sys
import time
import io
import uos as os
import gc
import urequests
import ujson as json
import ntptime

from micropython import const
from umqtt.simple import MQTTClient
import network

import my_secrets
import RingBuffer
import urandom

import micropython


@micropython.native
async def calibrate_average_rms(n: int) -> tuple:
    """calibrate the threshold value by taking the average of n samples. Assumes no 
       muons are present"""
    local_led2 = Pin(15, Pin.OUT) # local LED on pepper carrier board
    adc = ADC(0)  # Pin 26 is GP26, which is ADC0
    sumval = 0
    sum_squared = 0
    for _ in range(n):
        value = adc.read_u16()
        sumval += value
        sum_squared += value ** 2
        local_led2.toggle()
        await asyncio.sleep_ms(10) # wait 
    mean = sumval / n
    variance = (sum_squared / n) - (mean ** 2)
    standard_deviation = variance ** 0.5
    local_led2.value(0)
    return mean, standard_deviation


def init_sdcard():
    """ Initialize the SD card interface on the base board"""
# Define SPI pins -- see schematic for Pepper V2 board
    spi = machine.SPI(0, sck=machine.Pin(2), mosi=machine.Pin(3), miso=machine.Pin(0))
    cs = machine.Pin(1, machine.Pin.OUT)  # Chip select pin

    # Initialize SD card
    sd = sdcard.SDCard(spi, cs)

    # Mount the SD card using the uos module
    vfs = os.VfsFat(sd)
    os.mount(vfs, SD_DIRECTORY)

    # List the contents of the SD card
    print("Filesystem mounted at /sd")

    return sd

def unmount_sdcard():
    os.sync()
    os.umount(SD_DIRECTORY)
    print("SD card unmounted.")

def init_RTC():
    """set RTC to UTC. Uses NTP and falls back to worldtimeapi.org if NTP fails"""
    ntptime.host = 'ntp3.cornell.edu'
    ntptime.timeout = 2
    print(f"NTP host is {ntptime.host}")
    wait_time = 2
    success = False
    rtc = RTC()
    for _ in range(5):
        print("waiting for NTP time")
        try:
            led2.toggle()
            ntptime.settime()
            # if we get here, assume it succeeded (above throws exception on fail)
            print("NTP success: ", rtc.datetime())
            success = True
            break
        except OSError as e:
            print(f"NTP time setting failed. Check network connection. {e}")
        except Exception as e:
            print(f"unexpected error: {e}")
        time.sleep(wait_time)
        wait_time = wait_time * 2
    if not success:
        # fall back to urequests method
        print("NTP failed, trying worldtimeapi.org")
        try:
            response = urequests.get('http://worldtimeapi.org/api/ip')
            data = response.json()
            datetime_str = data['utc_datetime']
            print("datetime_str: ", datetime_str)
            year, month, day, hour, minute, second = map(int,
                                                         [datetime_str[0:4], datetime_str[5:7],
                                                          datetime_str[8:10], datetime_str[11:13],
                                                          datetime_str[14:16], datetime_str[17:19]])
            rtc.datetime((year, month, day, 0, hour, minute, second, 0))
            success = True
            print("RTC set to: ", rtc.datetime())
        except Exception as e:
            print(f"Failed to set RTC time: {e}")

    if not success:
        print("Failed to set RTC time")
        random_hour = urandom.getrandbits(5) % 24  # Generate a random hour (0-23)
        random_minute = urandom.getrandbits(6) % 60  # Generate a random minute (0-59)
        # Set RTC to a random time on 1/1/2024
        rtc.datetime((2024, 1, 1, 0, random_hour, random_minute, 0, 0))
    return get_iso8601_timestamp()


def get_iso8601_timestamp():
    """Return RTC time as an ISO8601 string in UTC with trailing 'Z'."""
    rtc = RTC()
    y, m, d, _, hh, mm, ss, _ = rtc.datetime()
    # No microsecond support in RTC; emit 000000 and mark as Z (UTC)
    return f"{y:04d}-{m:02d}-{d:02d}T{hh:02d}:{mm:02d}:{ss:02d}.000000Z"

def init_file(baseline, rms, threshold, reset_threshold, now, is_leader) -> io.TextIOWrapper:
    """ open file for writing, with date and time in the filename. write metadata. 
        return filehandle """
    now2 = time.localtime()
    year = now2[0]
    month = now2[1]
    day = now2[2]
    hour = now2[3]
    minute = now2[4]
    suffix = f"{year}{month:02d}{day:02d}_{hour:02d}{minute:02d}"
    # data file
    filename = f"/sd/muon_data_{suffix}.csv"
    # Reduce buffering to minimize RAM usage
    f = open(filename, "w", buffering=512, encoding='utf-8')
    f.write("baseline,stddev,threshold,reset_threshold,run_start_time,is_leader\n")
    if is_leader:
        leader = 1
    else:
        leader = 0
    f.write(f"{baseline:.1f}, {rms:.1f}, {threshold}, {reset_threshold}, {now}, {leader}\n")
    f.write("Muon Count,ADC,temperature_ADC,dt,t,t_wait,coinc\n")
    return f




# Path to the SD card directory where CSV files are located
SD_DIRECTORY = '/sd'





def usr_switch_pressed(pin):
    """interrupt handler for the user switch"""
    global switch_pressed
    if pin.value() == 1:
        switch_pressed = True

def check_leader_status():
    """check if this node is the leader or not. If the file /sd/is_secondary exists, then this is a secondary node"""
    try:
        os.stat("/sd/is_secondary")
        return False
    except OSError:
        return True


##################################################################
# Global variables
shutdown_request = False
restart_request = False
muon_count = 0
iteration_count = 0
rate = 0.
waited = 0
threshold = 0
reset_threshold = 0
is_leader = True
avg_time = 0.
rates = RingBuffer.RingBuffer(120,'f')
start_time_sec = 0
# Track last control message (raw bytes) to avoid re-processing retained/duplicate commands
last_control_msg = None
##################################################################
# MQTT configuration
MQTT_BROKER = getattr(my_secrets, 'MQTT_BROKER', 'pepper.physics.cornell.edu')
MQTT_PORT = getattr(my_secrets, 'MQTT_PORT', 1883)

##################################################################

### SET UP GPIO PINS
# set up switch on pin 16
usr_switch = Pin(16, Pin.IN, Pin.PULL_DOWN)
switch_pressed = False
usr_switch.irq(trigger=Pin.IRQ_RISING, handler=usr_switch_pressed)

# # HV supply -- active low pin to turn off
# # the high voltage power supply
# hv_power_enable.on() # turn on the HV supply


led1 = Pin('LED', Pin.OUT)
led2 = Pin(15, Pin.OUT) # local LED on pepper carrier board

# check if the network is active. It should already be 
# set up from boot.py
wlan = network.WLAN(network.STA_IF)
if not wlan.active():
    print("Wifi is not active")
    while True:
        led1.toggle()
        time.sleep(0.5)
        led2.toggle()
        time.sleep(0.1)
        led2.toggle()
        time.sleep(0.1)

now = init_RTC()
print(f"current time is {now}")
init_sdcard()


def get_device_id():
    """Read the device ID from id.txt and return as int"""
    try:
        with open('id.txt', 'r') as f:
            return int(f.read().strip())
    except Exception as e:
        print("Error reading device ID:", e)
        return 0

device_id = get_device_id()
#device_id = 3
print(f"Device ID: {device_id}")
MQTT_CLIENT_ID = f"cuwatch_{device_id:03d}".encode()

# Set MQTT topics after device_id is known
MQTT_TOPIC = f"telemetry/{device_id:03d}".encode()
MQTT_STATUS_TOPIC = f"status/{device_id:03d}".encode()
MQTT_CONTROL_TOPIC = f"control/{device_id:03d}/set".encode()

mqtt_client = None  # global MQTT client instance

def mqtt_connect():
    global mqtt_client
    try:
        # use a keepalive so broker can detect dead clients
        client = MQTTClient(MQTT_CLIENT_ID, MQTT_BROKER, port=MQTT_PORT, keepalive=60)
        client.set_callback(mqtt_message_callback)
        client.connect()
        client.subscribe(MQTT_CONTROL_TOPIC)
        mqtt_client = client
        print("Connected to MQTT broker")
        return client
    except Exception as e:
        print("MQTT connect failed:", e)
        mqtt_client = None
        return None

def ensure_mqtt_connected():
    """Ensure mqtt_client is connected; attempt reconnect if not."""
    global mqtt_client
    if mqtt_client is not None:
        return True
    # try to connect
    mqtt_connect()
    return mqtt_client is not None

def safe_publish(topic, msg):
    """Publish with reconnect attempts; return True if published."""
    global mqtt_client
    if not ensure_mqtt_connected():
        print("MQTT not connected, skipping publish")
        return False
    try:
        mqtt_client.publish(topic, msg)
        return True
    except Exception as e:
        print("Publish failed, will reconnect:", e)
        # drop old client and try reconnect
        mqtt_client = None
        ensure_mqtt_connected()
        return False

def mqtt_message_callback(topic, msg):
    global threshold
    global last_control_msg
    # Drop duplicate control payloads (e.g., retained messages on reconnect)
    try:
        if last_control_msg is not None and msg == last_control_msg:
            print("Duplicate control message ignored")
            return
    except Exception:
        pass # ignore comparison errors
    # remember this payload
    last_control_msg = msg

    def make_leader():
        global is_leader
        secondary_marker = "is_secondary"
        if secondary_marker in os.listdir('/sd'):
            os.remove(f"/sd/{secondary_marker}")
            print(f"Removed {secondary_marker}")
        else:
            print(f"{secondary_marker} does not exist")

        is_leader = True
    def make_follower():
        global is_leader
        secondary_marker = "is_secondary"
        if secondary_marker in os.listdir('/sd'):
            print(f"{secondary_marker} already exists")
        else:
            with open(f"/sd/{secondary_marker}", "w") as f:
                f.write("This node is a follower")
            print(f"Created {secondary_marker}")
        is_leader = False

    # we presume that the inputs were sanity-checked by the sender
    print("Received MQTT message on topic:", topic)
    print("Expected control topic:", MQTT_CONTROL_TOPIC)
    if topic == MQTT_CONTROL_TOPIC:
        try:
            # Decode bytes to string before loading JSON
            data = json.loads(msg.decode())
            print("Control message data:", data)
            if "threshold" in data:
                threshold = int(data["threshold"])
                print(f"Threshold updated via MQTT: {threshold}")
            if "reset_threshold" in data:
                global reset_threshold
                reset_threshold = int(data["reset_threshold"])
                print(f"Reset threshold updated via MQTT: {reset_threshold}")
            # Accept either {"new_run": true}, {"shutdown": true} or legacy string payloads
            if (isinstance(data, dict) and data.get("new_run")) or (isinstance(data, str) and data == "new_run"):
                print("Received new_run command via MQTT")
                global restart_request
                restart_request = True
                print("Restart request recv (MQTT)")
            if (isinstance(data, dict) and data.get("shutdown")) or (isinstance(data, str) and data == "shutdown"):
                print("Received shutdown command via MQTT")
                global shutdown_request
                shutdown_request = True
                print("Shutdown request recv (MQTT)")
            if "make_leader" in data:
                flag = bool(data["make_leader"])  # avoid shadowing function name
                global is_leader
                if flag:
                    print("Switching to leader mode via MQTT")
                    is_leader = True
                    make_leader()
                else:
                    print("Switching to secondary mode via MQTT")
                    is_leader = False
                    make_follower()
        except MemoryError:
            print("MemoryError in MQTT callback, running gc.collect()")
            gc.collect()
        except Exception as e:
            print("Failed to update threshold from MQTT:", e)
        finally:
            gc.collect()

async def mqtt_check_loop():
    """Periodically call check_msg and attempt reconnect on errors."""
    global mqtt_client
    while True:
        if not ensure_mqtt_connected():
            # wait and retry connect
            await asyncio.sleep(5)
            continue
        try:
            mqtt_client.check_msg()
        except OSError as e:
            print("MQTT check_msg error:", e)
            # force reconnection on socket errors
            mqtt_client = None
            ensure_mqtt_connected()
        except Exception as e:
            print("MQTT check_msg generic error:", e)
        await asyncio.sleep(5)

async def status_publish_loop(get_status_msg):
    """Publish status every 30s using safe_publish()."""
    while True:
        try:
            if ensure_mqtt_connected():
                status_msg = get_status_msg()
                if not safe_publish(MQTT_STATUS_TOPIC, status_msg):
                    print("Status publish failed; will retry next loop")
            else:
                print("Status publish skipped: MQTT not connected")
        except Exception as e:
            print("MQTT publish error (status):", e)
        await asyncio.sleep(30)

async def main():
    global muon_count, iteration_count, rate, waited, switch_pressed, avg_time
    global rates, threshold, reset_threshold, is_leader, start_time_sec
    print("main() started")
    gc.collect()
    l1t = led1.toggle
    l2on = led2.on
    l2off = led2.off
    adc = ADC(Pin(26))       # create ADC object on ADC pin, Pin 26
    temperature_adc = ADC(Pin(27))  # create ADC object on ADC pin Pin 27

    readout = adc.read_u16
    # # calibrate the threshold with HV off
    # hv_power_enable.off()
    # baseline, rms = calibrate_average_rms(500)

    # # 100 counts correspond to roughly (100/(2^16))*3.3V = 0.005V. So 1000 counts
    # # is 50 mV above threshold. the signal in Sally is about 0.5V.
    # threshold = int(round(baseline + 1000.))
    # reset_threshold = round(baseline + 50.)
    # print(f"baseline: {baseline}, threshold: {threshold}, reset_threshold: {reset_threshold}")

    # calibrate the threshold with HV on
    hv_power_enable = Pin(19, Pin.OUT)
    hv_power_enable.on()
    baseline, rms = await calibrate_average_rms(500)
    # 100 counts correspond to roughly (100/(2^16))*3.3V = 0.005V. So 1000 counts
    # is 50 mV above threshold. the signal in Sally is about 0.5V.
    threshold = int(round(baseline + 1000.))
    reset_threshold = round(baseline + 50.)
    print(f"baseline: {baseline}, threshold: {threshold}, reset_threshold: {reset_threshold}")

    coincidence_pin = None
    is_leader = check_leader_status()
    if is_leader:
        coincidence_pin = Pin(14, Pin.IN)
    else:
        coincidence_pin = Pin(14, Pin.OUT)
    print("is_leader is ", is_leader)

    global f
    f = init_file(baseline, rms, threshold, reset_threshold, now, is_leader)

    start_time_sec = time.time() # used for calculating runtime
    tmeas = time.ticks_ms
    tusleep = time.sleep_us
    start_time = tmeas()
    end_time = start_time
    iteration_count = 0
    muon_count = 0
    wait_counts = 0
    waited = 0
    dt = 0.
    global run_start_time
    run_start_time = start_time
    tlast = start_time
    temperature_adc_value = 0

    INNER_ITER_LIMIT = const(400_000)
    OUTER_ITER_LIMIT = const(20*INNER_ITER_LIMIT)
    YIELD_PERIOD_MS = const(25)  # tune: 20–50 ms works well

    dts = RingBuffer.RingBuffer(50)
    coincidence = 0
    print("start of data taking loop")
    loop_timer_time = tmeas()
    last_yield = loop_timer_time

    # MQTT setup
    global mqtt_client
    mqtt_client = mqtt_connect()
    # Start MQTT check loop (uses global mqtt_client)
    asyncio.create_task(mqtt_check_loop())

    def get_status_msg():
        return json.dumps({
            'rate': rate,
            'muon_count': muon_count,
            'threshold': threshold,
            'reset_threshold': reset_threshold,
            'baseline': baseline,
            'runtime': time.time() - start_time_sec,
            'is_leader': is_leader,
            'avg_time_ms': avg_time,
        })

    status_task_started = False
    first_event = True  # Track if this is the first event

    # DAQ main loop
    while True:
        iteration_count += 1
        if iteration_count % INNER_ITER_LIMIT == 0:
            rate = 1000./dts.calculate_average()
            tdiff = time.ticks_diff(tmeas(), loop_timer_time)
            avg_time = tdiff/INNER_ITER_LIMIT
            print(f"iter {iteration_count}, # {muon_count}, {rate:.1f} Hz, {gc.mem_free()} free, avg time {avg_time:.3f} ms")
            l1t()
            loop_timer_time = tmeas()
            # update rates ring buffer every half minute
            if time.ticks_diff(loop_timer_time, tlast) >= 30000:  # 30,000 ms = 30 seconds
                rates.append(round(rate, 2))
                tlast = loop_timer_time
            if iteration_count % OUTER_ITER_LIMIT == 0:
                print("flush file, iter ", iteration_count, gc.mem_free())
                f.flush()
                os.sync()
                gc.collect()
            # Start status publish loop after first INNER_ITER_LIMIT
            if not status_task_started:
                asyncio.create_task(status_publish_loop(get_status_msg))
                status_task_started = True
        adc_value = readout()  # Read the ADC value (0 - 65535)
        if adc_value > threshold: # we have a signal
            l2on()
            # Get the current time in milliseconds again
            end_time = tmeas()
            muon_count += 1
            wait_counts = 150
            if not is_leader:
                coincidence_pin.value(1)
            else:
                if coincidence_pin.value() == 1:
                    coincidence = 1
                else:
                    coincidence = 0
            # wait to drop beneath reset threshold
            while readout() > reset_threshold:
                wait_counts = wait_counts - 1
                tusleep(1)
                if is_leader and coincidence == 0: # latch value of coincidence
                    if coincidence_pin.value() == 1:
                        coincidence = 1
                if wait_counts == 0:
                    waited += 1
                    break
            # Calculate elapsed time in milliseconds
            dt = time.ticks_diff(end_time,start_time)
            dts.append(dt)
            temperature_adc_value = temperature_adc.read_u16()
            start_time = end_time
            # write to the SD card
            f.write(f"{muon_count}, {adc_value}, {temperature_adc_value}, {dt}, {end_time}, {wait_counts}, {coincidence}\n")
            l2off()
            if not is_leader:
                coincidence_pin.value(0)
            # Prepare event message
            event_data = {
                'device_number': int(device_id),
                'muon_count': muon_count,
                'adc_v': adc_value,
                'temp_adc_v': temperature_adc_value,
                'dt': dt,                 # milliseconds between this and previous hit
                'ts': get_iso8601_timestamp(),  # ISO-8601 UTC wall-clock time (Z)
                't_ms': end_time,         # monotonic ticks_ms for debugging
                'wait_cnt': wait_counts,
                'coincidence': coincidence
            }
            if first_event:
                print("sent first event string")
                # Add localtime as ISO8601 string
                lt = time.localtime()
                event_data['run_start'] = "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}".format(
                    lt[0], lt[1], lt[2], lt[3], lt[4], lt[5]
                )
                # Include run metadata for server-side tracking
                event_data['baseline'] = int(baseline)
                event_data['reset_threshold'] = int(reset_threshold)
                event_data['threshold'] = int(threshold)
                event_data['is_leader'] = is_leader
                first_event = False
            try:
                event_msg = json.dumps(event_data)
                safe_publish(MQTT_TOPIC, event_msg)
                gc.collect()  # Collect after event processing
            except Exception as e:
                print("MQTT publish error (event):", e)
        # Cooperative yield with a budget: only when idle and at most every YIELD_PERIOD_MS
        if adc_value <= threshold:
            now_ticks = tmeas()
            if time.ticks_diff(now_ticks, last_yield) >= YIELD_PERIOD_MS:
                await asyncio.sleep_ms(0)
                last_yield = now_ticks
        if iteration_count % 1_000 == 0:
            await asyncio.sleep_ms(0)
            gc.collect()  # Collect periodically
        if shutdown_request or switch_pressed or restart_request:
            print("tight loop shutdown, waited is ", waited)
            break
    f.close()
    hv_power_enable.off()
    print("exiting main loop")

# Run the main loop
try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("keyboard interrupt")
    try:
        f.close()
    except Exception:
        pass # ignore errors on file close
except Exception as e:
    sys.print_exception(e)
    try:
        f.close()
    except Exception:
        pass # ignore errors on file close
unmount_sdcard()
print("done -- run ending")

if restart_request:
    print("machine restarting")
    machine.reset()
