
from machine import ADC, Pin
import time
import machine
import uos
import sdcard



# Define SPI pins -- see schematic for Pepper V2 board
def init_sdcard():
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

sd = init_sdcard()

# Set up ADC on Pin 26 (GP26)
adc = ADC(Pin(26))  # Pin 26 is GP26, which is ADC0

# Get the current time in milliseconds
start_time = time.time_ns()
threshold = 12000 # random value for now
reset_threshold = 11950 # random 

muon_count = 0

# open file for writing, with date and time in the filename
filename = "/sd/muon_data_" + time.strftime("%Y%m%d-%H%M%S") + ".csv"
with open(filename, "w") as f:
    f.write("Muon Count, ADC Value, Time (ns)\n")
    # Infinite loop to read and print ADC value
    while True:
        adc_value = adc.read_u16()  # Read the ADC value (0 - 65535)
        if ( adc_value > threshold ) :
            voltage = adc_value * 3.3 / 65535  # Convert to voltage (assuming 3.3V reference)
            # Get the current time in milliseconds again
            end_time = time.time_ns()
            muon_count = muon_count + 1

            # Calculate elapsed time in milliseconds
            elapsed_time = (end_time - start_time) # what about wraparound
            # write to the SD card
            f.write(f"{muon_count}, {adc_value}, {elapsed_time}\n")

            wait_counts = 0
            # wait to drop beneath reset threshold
            while ( adc.read_u16() > reset_threshold ):
                wait_counts = wait_counts + 1
                time.sleep(.01)
                #print(adc.read_u16())
            print("wait counts", wait_counts)
            # sync the file
            f.flush()

# Unmount the SD card
uos.umount("/sd")
