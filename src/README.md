# Instructions

All code assumes you have the micropython repl installed. Instructions for doing so [can be found here](https://www.raspberrypi.com/documentation/microcontrollers/micropython.html).

For the sdcard you need to install the sdcard library from micropi-libs also; see instructions below.

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

## Program flow as of 11/5/2024
When the code starts, the first thing that happens is that the Pico tries to connect to the wifi. If the LEDs start blinking in a 2:1 pattern, that means that connection to wifi was unsuccessful. Probably the `my_secrets.py` file needs to be updated on the pico for the local network.

After connecting to WIFI, the board tries to get the current time by querying a remote web page (http://worldtimeapi.org). This is used to set the time stamp for the data collection.

Next, the red LED on the pepper board will blink rapidly for about 8 seconds. This is where the baseline of the ADC is being measured. 

Next, the SD card is mounted and the data file is opened for writing. The first two lines of the data file contain metadata about the run (time, threshold, baseline, etc.) After this, the web server is started up and the data collection starts.

To stop data collection, you can press the USR button (the one on the carrier board closer to the Pico.) This stops the data readout, closes the data file and unmounts the SD card. The web server also stops then. To reboot the pico, hit the other button (RESET*). RESET doesn't cleanly close the data file and you will probbaly lose some data.

The web server rate graph stores all the data on the client side (i.e., your browser), so the data will gradually populate over an hour. It will also not populate if your web browser is in the background, it appers. you can download data from the web page or by putting the microSD card into your computer. the download from the web page is slow (about 12 kb/sec), so it takes a long time for big data files. Do not navigate away from the download page while the download is happening -- it will interrupt the download. Data collection continues during the download process.


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

### Automatic startup
To have the web page and readout run by default, the python file needs to be copied to the pico as `main.py`:
```shell
mpremote fs cp asynchio4.py :main.py
```
Micropython automatically runs the file called `main.py` when it starts. 

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
