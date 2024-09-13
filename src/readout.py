
from machine import ADC, Pin
import time

# Set up ADC on Pin 26 (GP26)
adc = ADC(Pin(26))  # Pin 26 is GP26, which is ADC0

# Get the current time in milliseconds
start_time = time.time_ns()
threshold = 12000 # random value for now
reset_threshold = 11950 # random 

muon_count = 0

# Infinite loop to read and print ADC value
while True:
    adc_value = adc.read_u16()  # Read the ADC value (0 - 65535)
    if ( adc_value > threshold ) :
        voltage = adc_value * 3.3 / 65535  # Convert to voltage (assuming 3.3V reference)
        # Get the current time in milliseconds again
        end_time = time.time_ns()
        muon_count = muon_count + 1

        # Calculate elapsed time in milliseconds
        elapsed_time = time.ticks_diff(end_time, start_time)
        # write to the SD card
        print(muon_count, adc_value, elapsed_time)

        wait_counts = 0
        # wait to drop beneath reset threshold
        while ( adc.read_u16() > reset_threshold ):
            wait_counts = wait_counts + 1
            time.sleep(.01)
            #print(adc.read_u16())
        print("wait counts", wait_counts)
