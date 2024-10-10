
from machine import ADC, Pin, RTC, WDT
import network
import time
import machine
import uos
import sdcard
import urequests
import ujson
import sys
import logging
import gc

import my_secrets


# Init Wi-Fi Interface
def init_wifi(ssid, password):
    """connect to the designated wifi network"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    # Connect to your network
    if ( password == None ):
        wlan.connect(ssid)
    else:
        wlan.connect(ssid, password)
    # Wait for Wi-Fi connection
    connection_timeout = 30
    print('Waiting for Wi-Fi connection ...', end="")
    cycle = [ '   ', '.  ', '.. ', '...']
    i = 0
    led2.value(1)
    led1.value(0)
    while connection_timeout > 0:
        if wlan.status() >= network.STAT_GOT_IP:
            break
        connection_timeout -= 1
        print(f"\b\b\b{cycle[i]}", end="")
        i = (i + 1) % 4
        time.sleep(1)
        led1.toggle()
        led2.toggle()
    
    print("\b\b\b   ")
    # Check if connection is successful
    if wlan.status() != network.STAT_GOT_IP:
        print('Failed to connect to Wi-Fi')
        return False
    else:
        print('Connection successful!')
        network_info = wlan.ifconfig()
        print('IP address:', network_info[0])
        return True
    
# 
def init_RTC():
    """set date and time in RTC. Assumes we are on the network."""
    # Get the date and time for the public IP address our node is associated with
    url = 'http://worldtimeapi.org/api/ip'
    response = urequests.get(url)
    try:
        if response.status_code != 200:
            print('Error getting time from the internet')
            return None
        data = ujson.loads(response.text)
    finally:
        response.close()
    # put current time into RTC
    dttuple = (int(data['datetime'][0:4]), # year
                int(data['datetime'][5:7]), # month
                int(data['datetime'][8:10]), # day
                int(data['day_of_week']), # day of week
                int(data['datetime'][11:13]), # hour
                int(data['datetime'][14:16]), # minute
                int(data['datetime'][17:19]), # second
                0) # subsecond, not set here
    rtc = RTC()
    rtc.datetime(dttuple)
    return data['datetime']

# Define SPI pins -- see schematic for Pepper V2 board
def init_sdcard():
# Define SPI pins -- see schematic for Pepper V2 board
    spi = machine.SPI(0, sck=machine.Pin(2), mosi=machine.Pin(3), miso=machine.Pin(0))
    cs = machine.Pin(1, machine.Pin.OUT)  # Chip select pin

    # Initialize SD card
    sd = sdcard.SDCard(spi, cs)

    # Mount the SD card using the uos module
    vfs = uos.VfsFat(sd)
    uos.mount(vfs, "/sd")

    # List the contents of the SD card
    print("Filesystem mounted at /sd")

    return sd

def unmount_sdcard():
    uos.sync()
    uos.umount("/sd")
    print("SD card unmounted.")


### logging
class CustomFormatter(logging.Formatter):
    def format(self, record):
        # Get the current local time as a tuple
        timestamp = time.localtime()
        # Format the tuple into a human-readable string (YYYY-MM-DD HH:MM:SS)
        time_str = '{}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(
            timestamp[0], timestamp[1], timestamp[2],
            timestamp[3], timestamp[4], timestamp[5]
        )
        # Format the final log message, combining the time with the original message
        log_message = f"{time_str} - {record.levelname} - {record.name} - {record.message}"
        return log_message

def init_logging(log_file: str):
    # Create a logger object
    logger = logging.getLogger('pepper')
    logger.setLevel(logging.DEBUG)  # Set the logging level to DEBUG or any level you prefer

    # Create a file handler to log to the specified file
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)

    # Create a stream handler to log to standard output
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG)

    # Use the custom formatter without 'asctime', injecting the time manually into the message
    formatter = CustomFormatter('%(message)s - %(name)s - %(levelname)s')

    # Set the formatter for both handlers
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)

    # Add handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger
def calibrate_average_rms(adc, n):
    """calibrate the threshold value by taking the average of n samples. Assumes no muons are present"""
    sum = 0
    sum_squared = 0
    for i in range(n):
        value = adc.read_u16()
        sum += value
        sum_squared += value ** 2
        led2.toggle()
        time.sleep_ms(25) # wait 
    mean = sum / n
    variance = (sum_squared / n) - (mean ** 2)
    standard_deviation = variance ** 0.5
    led2.value(0)
    return mean, standard_deviation


def usr_switch_pressed(pin):
    """interrupt handler for the user switch"""
    global switch_pressed
    if pin.value() == 1:
        switch_pressed = True

def led_on_oneshot(timer):
    """Callback function to turn off the LED after 1 ms"""
    global led2
    led2.off()
    timer.deinit()

timer = machine.Timer(-1)

def turn_on_led_oneshot():
    """Turn on the LED and set a timer to turn it off after x ms"""
    global led2, timer
    led2.on()
    timer.init(period=2, mode=machine.Timer.ONE_SHOT, callback=led_on_oneshot)

### end of function definitions
# setup LEDs
led1 = Pin('LED', Pin.OUT)
led2 = Pin(15, Pin.OUT) # local LED on pepper carrier board
led1.value(0)
led2.value(0)

# reset cause
reset_cause = machine.reset_cause()
print("reset cause", reset_cause)


if (not init_wifi(my_secrets.SSID, my_secrets.PASS) ):
    print("Couldn't initialize wifi")
    while True:
        led2.toggle()
        led1.toggle()
        time.sleep(1)
        
now = init_RTC()
print(f"current time is {now}")

# Set up ADC on Pin 26 (GP26)
adc = ADC(Pin(26))  # Pin 26 is GP26, which is ADC0
temperature_adc = ADC(Pin(27)) #local temperature sensor
temperature_adc2 = ADC(4) #internal temperature sensor


# set up switch on pin 16
usr_switch = Pin(16, Pin.IN, Pin.PULL_DOWN)
switch_pressed = False
usr_switch.irq(trigger=Pin.IRQ_RISING, handler=usr_switch_pressed)

threshold = 0
reset_threshold = 0

muon_count = 0

run_start_time = time.ticks_ms()
end_time = 0  


sd = init_sdcard()

# this try block allows us to close the file and unmount the sd card if we get an exception
try:
    # open file for writing, with date and time in the filename
    now = time.localtime()
    year = now[0]
    month = now[1]
    day = now[2]
    hour = now[3]
    minute = now[4]
    suffix = f"{year}{month:02d}{day:02d}_{hour:02d}{minute:02d}"
    # log file
    logger = init_logging(f"/sd/log_{suffix}.txt")

    # calibrate the adc
    print("Calibrating ...")
    led2.value(1)
    baseline, rms = calibrate_average_rms(adc, 500)
    logger.info(f"baseline {baseline:.1f} rms {rms:.1f}")
    #print(f"baseline is {baseline:.1f} pm {rms:.1f}")
    #threshold = baseline + 3.2*rms
    #threshold = round(baseline + 3.*rms)
    threshold = round(baseline + 200.)
    reset_threshold = round(baseline + 50.)
    logger.info(f"calibrated threshold {threshold} and reset threshold {reset_threshold}")
    led2.value(0)
    time.sleep(5)
    # data file
    filename = f"/sd/muon_data_{suffix}.csv"
    logger.info(f"writing to {filename}")
    # turn on the watchdog
    #wdt = WDT(timeout=8_000)  # enable it with a timeout of 8 seconds
    with open(filename, "w", buffering=10240) as f:
        f.write(f"baseline, {baseline:.1f}\n")
        f.write(f"stddev, {rms:.1f}\n")
        f.write(f"threshold, {threshold}\n")
        f.write(f"reset_threshold, {reset_threshold}\n")

        f.write("Muon Count, ADC, ADCM, temperature_ADC, temperature_ADC2, dt, t, t_wait\n")
        # Infinite loop to read and print ADC value
        # Get the current time in milliseconds
        start_time = time.ticks_ms()
        end_time = start_time
        iter = 0
        while True:
            #wdt.feed()
            led1.toggle()
            iter = iter + 1
            if iter % 100_000 == 0:
                logger.info(f"iter {iter}")
                f.flush()
                uos.sync()
            adc_value = adc.read_u16()  # Read the ADC value (0 - 65535)
            #print(adc_value)
            if ( adc_value > threshold ) :
                # Get the current time in milliseconds again
                end_time = time.ticks_ms()
                muon_count = muon_count + 1
                # print out when muon_count is a multiple of 10
                if muon_count % 50 == 0:
                    led2.off()
                    rate = 1000.*muon_count/time.ticks_diff(end_time, run_start_time)
                    logger.info(f"#: {muon_count}, {rate:.1f} Hz, {gc.mem_free()} free")
                    #gc.collect()
                led2.on()

                wait_counts = 100
                # wait to drop beneath reset threshold
                # time.sleep_us(3)
                adc_curr_val = adc.read_u16()
                adc_max_val = adc_curr_val
                while ( adc_curr_val > reset_threshold ):
                    wait_counts = wait_counts - 1
                    time.sleep_us(3)
                    if ( wait_counts == 0 ):
                        logger.warning(f"waited too long, adc value {adc_curr_val}")
                        break
                    led1.toggle()
                    adc_curr_val = adc.read_u16()
                    adc_max_val = max(adc_max_val, adc_curr_val)
                #turn_on_led_oneshot()
                # Calculate elapsed time in milliseconds
                dt = time.ticks_diff(end_time,start_time) # what about wraparound
                temperature_adc_value = temperature_adc.read_u16()
                temperature_adc_value2 = temperature_adc2.read_u16()
                start_time = end_time
                # write to the SD card
                f.write(f"{muon_count}, {adc_value}, {adc_max_val}, {temperature_adc_value}, {temperature_adc_value2}, {dt}, {end_time}, {wait_counts}\n")
                led2.off()
            #time.sleep_us(20)
            if switch_pressed:
                logger.info("switch pressed, exiting")
                break
except Exception as e:
    print("exception", e)
    logger.exception(f"exception {e}")
    raise
finally:
    print("muon count", muon_count)
    print(f"thresholds were {threshold} and {reset_threshold}")
    print(f"data written to {filename}")
    # calculate rate
    elapsed_time = time.ticks_diff(end_time, run_start_time) / 1000.0
    print(f"elapsed time {elapsed_time:.2f} seconds")
    rate = muon_count / elapsed_time
    logger.info(f"muon count {muon_count}, rate {rate:.2f} muons/sec")
    logging.shutdown()
    unmount_sdcard()
