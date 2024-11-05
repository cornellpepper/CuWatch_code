# Instructions

All code assumes you have the micropy repl installed.

For the sdcard you need to install the sdcard library from micropi-libs also; see comment inline in code. Using `mpremote` the commmand is as follows.

To get mpremote, suggest you follow the instructions here and install via pip the following two packages:
```
pip install --user mpremote
pip install --user mpy-cross
```
The former is a command-line tool for connecting to the micropython repl; the second is a way to cross-compile the microdot web server, which is needed because the compilation step can't be done on the pico itself.

Then install the packages required.
```shell
mpremote mip install sdcard logger 
```

## Newer files that are of interest (10/21/2024)
- readout.py: readout w/o web server. Obsolete.
- asynchio4.py: current version that uses `asyncio` and [microdot](https://microdot.readthedocs.io/en/latest) for web services, and also provides the readout.
    - this requires you to install the following files
    1. `microdot.py` and `__init__.py` from the microdot repo. Pre-compile using mpy-cross to generate `mpy` file and install that to save memory.
    2. `mpy-cross microdot.py; mpremote fs cp microdot.mpy :`; same for `__init__.py`
    3. `RingBuffer.py` from the local repo, install via `mpremote fs cp RingBuffer.py :`
    4. Create and install `my_secrets.py` which must look like this e.g., for RedRover
```
PASS=None
SSID=RedRover
```

    5. Run via `mpremote run asynchio4.py` from the terminal.


## Files as of 2024-10-01

- basic_webserver.py - a simple webserver that serves a single page with a button that toggles the onboard LED. Not suitable for anything but the most basic testing.
- blink.py - a simple blink program that toggles the onboard LED.
- blink2.py - a simple blink program that toggles the onboard LED and the LED on the Pepper baseboard.
- findmac.py - a program that prints the MAC address of the Rpi Pico-W.
- readout.py - main program to read out the digitized muon signals.
- sdtest.py - test program for the sdcard. Mounts SD card, writes a file, reads it back, and prints the contents, and then unmounts the SD card.
- server_check.py - program to be run on a PC to see if the web server on the pico is up over an extended time period (reliability test)
- setrtc.py - set the RTC on the pico using the time from an online reference.
- webserver.py - webserver using _threads module to try to use both cores on RP2040. Does not work.
- webserver2.py - web server using asyncio (cooperative multitasking) module. Works. Does not use 2nd core.
