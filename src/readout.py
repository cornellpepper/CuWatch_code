
from machine import ADC, Pin, RTC
import network
import time
import machine
import uos
import sdcard
import urequests
import ujson
import sys


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
    connection_timeout = 10
    while connection_timeout > 0:
        print(wlan.status())
        if wlan.status() >= 3:
            break
        connection_timeout -= 1
        print('Waiting for Wi-Fi connection...')
        time.sleep(1)
    # Check if connection is successful
    if wlan.status() != 3:
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
    print(uos.listdir("/sd"))
    return sd

def unmount_sdcard():
    uos.umount("/sd")
    print("SD card unmounted.")


def calibrate_average_rms(adc, n):
    """calibrate the threshold value by taking the average of n samples. Assumes no muons are present"""
    sum = 0
    sum_squared = 0
    for i in range(n):
        value = adc.read_u16()
        sum += value
        sum_squared += value ** 2
        time.sleep_ms(10) # wait 10 ms
    mean = sum / n
    variance = (sum_squared / n) - (mean ** 2)
    standard_deviation = variance ** 0.5
    return mean, standard_deviation

### end of function definitions

init_wifi("SSID", "PASSWORD")
now = init_RTC()
print(f"current time is {now}")

sd = init_sdcard()

# Set up ADC on Pin 26 (GP26)
adc = ADC(Pin(26))  # Pin 26 is GP26, which is ADC0

threshold = 13050 # random value for now
reset_threshold = 12900 # random 

muon_count = 0

# this try block allows us to close the file and unmount the sd card if we get an exception
try:
    # open file for writing, with date and time in the filename
    now = time.localtime()
    year = now[0]
    month = now[1]
    day = now[2]
    hour = now[3]
    minute = now[4]
    filename = f"/sd/muon_data_{year}{month:02d}{day:02d}_{hour:02d}{minute:02d}.csv"
    # calibrate the adc
    print("calibrating")
    baseline, rms = calibrate_average_rms(adc, 250)
    threshold = baseline + 3.2*rms
    reset_threshold = baseline - 3*rms
    print("calibrated threshold", threshold, reset_threshold)
    time.sleep(5)
    print(f"writing to {filename}")
    with open(filename, "w") as f:
        f.write("Muon Count, ADC Value, dt, time\n")
        # Infinite loop to read and print ADC value
        # Get the current time in milliseconds
        start_time = time.ticks_ms()
        end_time = start_time
        while True:
            adc_value = adc.read_u16()  # Read the ADC value (0 - 65535)
            #print(adc_value)
            if ( adc_value > threshold ) :
                #voltage = adc_value * 3.3 / 65535  # Convert to voltage (assuming 3.3V reference)
                # Get the current time in milliseconds again
                end_time = time.ticks_ms()
                muon_count = muon_count + 1

                # Calculate elapsed time in milliseconds
                dt = time.ticks_diff(end_time,start_time) # what about wraparound
                # write to the SD card
                f.write(f"{muon_count}, {adc_value}, {dt}, {end_time}\n")
                start_time = end_time
                wait_counts = 0
                print(adc_value, dt)
                # wait to drop beneath reset threshold
                time.sleep_ms(10)
                while ( adc.read_u16() > reset_threshold ):
                    wait_counts = wait_counts + 1
                    time.sleep_ms(10)
                    if ( wait_counts > 1000 ):
                        print("waited too long", adc.read_u16())
                        break
                    #print(adc.read_u16())
                print("wait counts", wait_counts)
                # sync the file
                f.flush()
finally:
    unmount_sdcard()
    print("muon count", muon_count)
    print(f"thresholds were {threshold} and {reset_threshold}")
    print(f"ending time is {time.localtime()}")
    print(f"data written to {filename}")
