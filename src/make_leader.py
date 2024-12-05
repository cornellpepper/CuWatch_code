# on Pepper v2
# use SPI 0
# SPIO Rx  = GPIO 0
# SPIO CS* = GPIO 1
# SPIO SC  = GPIO 2
# SPIO TX  = GPIO 3

#  mpremote connect /dev/cu.usbmodem1401 mip install sdcard   # install sdcard module

import machine
import uos
import sdcard

print("SD card example")

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

# Check if the file exists and remove it if it does
file_path = "/sd/is_secondary"
if file_path in uos.listdir("/sd"):
    uos.remove(file_path)
    print(f"Removed {file_path}")
else:
    print(f"{file_path} does not exist")



# Unmount the SD card
uos.umount("/sd")
print("SD card unmounted.")
