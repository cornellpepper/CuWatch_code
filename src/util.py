#! /usr/bin/env python

import machine
import sdcard
import os
import time
import ntptime
import urequests
import io
import urandom

# Path to the SD card directory where CSV files are located
SD_DIRECTORY = '/sd'

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

def init_RTC(led2: machine.Pin) -> str:
    """set RTC to UTC. Uses NTP and falls back to worldtimeapi.org if NTP fails"""
    ntptime.host = 'ntp3.cornell.edu'
    ntptime.timeout = 2
    print(f"NTP host is {ntptime.host}")
    wait_time = 2
    success = False
    rtc = machine.RTC()
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
            year, month, day, hour, minute, second = map(int, datetime_str.split('T')[0].split('-') + datetime_str.split('T')[1].split(':'))
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


def get_iso8601_timestamp(timezone_offset="+00:00"):
    """return RTC time as an ISO8601 string, default to UTC TZ"""
    rtc = machine.RTC()
    dt = rtc.datetime()

    # NOTE: no microsecond support in RTC, so we use 000000
    timestamp = "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.{:06d}{}".format(
        dt[0], dt[1], dt[2], dt[4], dt[5], dt[6], 0, timezone_offset
    )

    return timestamp

def init_file(baseline, rms, threshold, reset_threshold, now, is_leader) -> io.TextIOWrapper:
    """ open file for writing, with date and time in the filename. write metadata. return filehandle """
    now2 = time.localtime()
    year = now2[0]
    month = now2[1]
    day = now2[2]
    hour = now2[3]
    minute = now2[4]
    suffix = f"{year}{month:02d}{day:02d}_{hour:02d}{minute:02d}"
    # data file
    filename = f"/sd/muon_data_{suffix}.csv"
    f = open(filename, "w", buffering=10240, encoding='utf-8')
    f.write("baseline,stddev,threshold,reset_threshold,run_start_time,is_leader\n")
    if is_leader:
        leader = 1
    else:
        leader = 0
    f.write(f"{baseline:.1f}, {rms:.1f}, {threshold}, {reset_threshold}, {now}, {leader}\n")
    f.write("Muon Count,ADC,temperature_ADC,dt,t,t_wait,coinc\n")
    return f


