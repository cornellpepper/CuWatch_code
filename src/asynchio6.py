"""MQTT client version of the code, where the Pico-W is an MQTT client and sends 
the data to an MQTT broker running on a remote server based on the raspberry Pi.
this version uses an asynchio version of mqtt for micropython."""

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
from mqtt_as import MQTTClient, config
import asyn  # mqtt_as async helper
import network
import rp2 

import my_secrets
import RingBuffer
import urandom
from asyn import Event  


shutdown_request = False



@micropython.native
async def calibrate_average_rms(n: int) -> tuple:
    """calibrate the threshold value by taking the average of n samples. 
       Assumes no muons are present"""
    led2 = Pin(15, Pin.OUT) # local LED on pepper carrier board
    adc = ADC(0)  # Pin 26 is GP26, which is ADC0
    sumval = 0
    sum_squared = 0
    for _ in range(n):
        value = adc.read_u16()
        sumval += value
        sum_squared += value ** 2
        led2.toggle()
        await asyncio.sleep_ms(10) # wait 
    mean = sumval / n
    variance = (sum_squared / n) - (mean ** 2)
    standard_deviation = variance ** 0.5
    led2.value(0)
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
    """set RTC to UTC. Uses NTP and falls back to worldtimeapi.org if NTP 
       fails"""
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
        except Error as e:
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
            year, month, day, hour, minute, second = map(int, datetime_str.split('T')[0].split('-') + datetime_str.split('T')[1].split(':'))
            rtc.datetime((year, month, day, 0, hour, minute, second, 0))
            success = True
            print("RTC set to: ", rtc.datetime())
        except Error as e:
            print(f"Failed to set RTC time: {e}")
    
    if not success:
        print("Failed to set RTC time")
        random_hour = urandom.getrandbits(5) % 24  # Generate a random hour (0-23)
        random_minute = urandom.getrandbits(6) % 60  # Generate a random minute (0-59)
        # Set RTC to a random time on 1/1/2020
        rtc.datetime((2020, 1, 1, 0, random_hour, random_minute, 0, 0))
    return get_iso8601_timestamp()


def get_iso8601_timestamp(timezone_offset="+00:00"):
    """return RTC time as an ISO8601 string, default to UTC TZ"""
    rtc = RTC()
    dt = rtc.datetime()

    # NOTE: no microsecond support in RTC, so we use 000000
    timestamp = "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.{:06d}{}".format(
        dt[0], dt[1], dt[2], dt[4], dt[5], dt[6], 0, timezone_offset
    )

    return timestamp

def init_file(baseline, rms, threshold, reset_threshold, now, is_leader) -> io.TextIOWrapper:
    """ open file for writing, with date and time in the filename. write 
        metadata. return filehandle """
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
    f = open(filename, "w", buffering=128, encoding='utf-8')  # reduced buffer
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
    """check if this node is the leader or not. If the file /sd/is_secondary 
        exists, then this is a secondary node"""
    try:
        os.stat("/sd/is_secondary")
        return False
    except OSError:
        return True


##################################################################
# MQTT configuration
MQTT_BROKER = getattr(my_secrets, 'MQTT_BROKER', '10.49.72.125')
MQTT_PORT = getattr(my_secrets, 'MQTT_PORT', 1883)
MQTT_CLIENT_ID = getattr(my_secrets, 'MQTT_CLIENT_ID', b"cuwatch_node")

# mqtt_as config
config['server'] = MQTT_BROKER
config['port'] = MQTT_PORT
config['client_id'] = MQTT_CLIENT_ID
config['ssid'] = getattr(my_secrets, 'WIFI_SSID', '')
config['wifi_pw'] = getattr(my_secrets, 'WIFI_PASSWORD', '')

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
    """Read the device ID from /sd/id.txt and return as int"""
    try:
        with open('/sd/id.txt', 'r') as f:
            return int(f.read().strip())
    except Exception as e:
        print("Error reading device ID:", e)
        return 0

device_id = get_device_id()
device_id = 3 # FIXME
print(f"Device ID: {device_id}")

# Set MQTT topics after device_id is known
MQTT_TOPIC = f"telemetry/{device_id:03d}".encode()
MQTT_STATUS_TOPIC = f"status/{device_id:03d}".encode()
MQTT_CONTROL_TOPIC = f"control/{device_id:03d}/set".encode()


# Add event for control topic
mqtt_control_event = Event()

async def mqtt_event_handler(mqtt_client, control_event, threshold_ref):
    while True:
        await control_event.wait()
        while mqtt_client.queue:
            topic, msg, _ = mqtt_client.queue.popleft()
            if topic == MQTT_CONTROL_TOPIC:
                try:
                    data = json.loads(msg.decode())
                    if "threshold" in data:
                        threshold_ref[0] = int(data["threshold"])
                        print(f"Threshold updated via MQTT: {threshold_ref[0]}")
                except MemoryError:
                    print("MemoryError in MQTT event handler, running gc.collect()")
                    gc.collect()
                except Exception as e:
                    print("Failed to update threshold from MQTT:", e)
                finally:
                    gc.collect()
            # Release references
            topic = None
            msg = None
        control_event.clear()
        gc.collect()

async def status_publish_loop(mqtt_client, get_status_msg):
    while True:
        try:
            status_msg = get_status_msg()
            await mqtt_client.publish(MQTT_STATUS_TOPIC, status_msg)
            print("sent status message")
        except Exception as e:
            print("MQTT publish error (status):", e)
        gc.collect()  # collect after publish
        await asyncio.sleep(30) # send every 30 seconds

async def main():
    global switch_pressed
    # All state is local to main()
    muon_count = 0
    iteration_count = 0
    rate = 0.
    waited = 0
    threshold = 0
    reset_threshold = 0
    is_leader = True
    avg_time = 0.
    start_time_sec = 0
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

    f = init_file(baseline, rms, threshold, reset_threshold, now, is_leader)

    start_time_sec = time.time() # used for calculating runtime
    tmeas = time.ticks_ms
    tusleep = time.sleep_us
    start_time = tmeas()
    end_time = start_time
    iteration_count = 0
    muon_count = 0
    waited = 0
    wait_counts = 0
    waited = 0
    dt = 0.
    run_start_time = start_time
    tlast = start_time
    temperature_adc_value = 0

    INNER_ITER_LIMIT = const(400_000)
    OUTER_ITER_LIMIT = const(20*INNER_ITER_LIMIT)

    dts = RingBuffer.RingBuffer(10)  # reduced from 50 to 10
    coincidence = 0
    print("start of data taking loop")
    loop_timer_time = tmeas()

    # MQTT setup
    threshold_ref = [threshold]  # use a mutable container to allow update in handler
    mqtt_client = MQTTClient(config)
    await mqtt_client.connect()
    print("Connected to MQTT broker")
    await mqtt_client.subscribe(MQTT_CONTROL_TOPIC, 1)
    print(f"Subscribed to topic: {MQTT_CONTROL_TOPIC}")

    # Register event for the control topic
    mqtt_client.set_event(MQTT_CONTROL_TOPIC, mqtt_control_event)
    asyncio.create_task(mqtt_event_handler(mqtt_client, mqtt_control_event, threshold_ref))

    def get_status_msg():
        # Use compact separators for JSON
        return json.dumps({
            'rate': rate,
            'muon_count': muon_count,
            'threshold': threshold_ref[0],
            'reset_threshold': reset_threshold,
            'runtime': time.time() - start_time_sec
        }, separators=(',', ':'))

    status_task_started = False
    first_event = True  # Track if this is the first event

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
                asyncio.create_task(status_publish_loop(mqtt_client, get_status_msg))
                status_task_started = True
        adc_value = readout()  # Read the ADC value (0 - 65535)
        if adc_value > threshold_ref[0]:
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
                'dt': dt,
                'ts': end_time,
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
                first_event = False
            try:
                event_msg = json.dumps(event_data, separators=(',', ':'))  # compact JSON
                await mqtt_client.publish(MQTT_TOPIC, event_msg)
                gc.collect()  # Collect after event processing
            except Exception as e:
                print("MQTT publish error (event):", e)
            finally:
                event_msg = None  # release memory
                event_data = None
        if iteration_count % 1_000 == 0:
            await asyncio.sleep_ms(0)
            gc.collect()  # force collection more often
        if shutdown_request or switch_pressed or restart_request:
            print("tight loop shutdown, waited is ", waited)
            break
    f.close()
    f = None  # release file handle


# Run the main loop
try:
    asyn.run(main())
except KeyboardInterrupt:
    print("keyboard interrupt")
    try:
        f.close()
    except:
        pass
    unmount_sdcard()
    print("done")
except Exception as e:
    sys.print_exception(e)
    try:
        f.close()
    except:
        pass
    unmount_sdcard()
    print("done")

if restart_request:
    machine.reset()
