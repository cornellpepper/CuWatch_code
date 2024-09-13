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

# Writing and reading a test file
with open("/sd/test.txt", "w") as f:
    f.write("Hello, Raspberry Pi Pico W with SD card!\n")

print("File written successfully.")

# Read the file back
with open("/sd/test.txt", "r") as f:
    print("File content:")
    print(f.read())

# Unmount the SD card
uos.umount("/sd")
print("SD card unmounted.")
