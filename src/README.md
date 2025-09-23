# Instructions

All code assumes you have the micropython repl installed. Instructions for doing so [can be found here](https://www.raspberrypi.com/documentation/microcontrollers/micropython.html).

To get mpremote, suggest you follow the instructions here and install via pip the following two packages:

```shell
pip install --user mpremote
pip install --user mpy-cross
```

The former is a command-line tool for connecting to the micropython repl; the second is a way to cross-compile the microdot web server, which is needed because the compilation step can't be done on the pico itself.

Then install the packages required. A handy script is in the repo.

```shell
./install.sh
```
This script will, using `mpremote`, wipe the internal flash file system, install the necessary packages from micropython and the local repository and download the appropriate version of the web server [[microdot](https://microdot.readthedocs.io/en/latest/index.html)] and install the required files from it.

## Program flow as of 11/5/2024

When the code starts, the first thing that happens is that the Pico tries to connect to the wifi. If the LEDs start blinking in a 2:1 pattern, that means that connection to wifi was unsuccessful. Probably the `my_secrets.py` file needs to be updated on the pico for the local network.

After checking if we are connected to WIFI, the board tries to get the current time by querying an ntp server, and, if that fails, a remote web page (http://worldtimeapi.org). This is used to set the time stamp for the data collection.

Next, the red LED on the pepper board will blink rapidly for about 8 seconds. This is where the baseline of the ADC is being measured.

Next, the SD card is mounted and the data file is opened for writing. The first two lines of the data file contain metadata about the run (time, threshold, baseline, etc.) After this, the web server is started up and the data collection starts.

To stop data collection, you can press the USR button (the one on the carrier board closer to the Pico.) This stops the data readout, closes the data file and unmounts the SD card. The web server also stops then. To reboot the pico, hit the other button (RESET*). RESET doesn't cleanly close the data file and you will probbaly lose some data.

The web server rate graph stores all the data on the client side (i.e., your browser), so the data will gradually populate over an hour. It will also not populate if your web browser is in the background, it appers. you can download data from the web page or by putting the microSD card into your computer. the download from the web page is slow (about 12 kb/sec), so it takes a long time for big data files. Do not navigate away from the download page while the download is happening -- it will interrupt the download. Data collection continues during the download process.


## Current files used in the running device

- asynchio4.py: current version that uses `asyncio` and [microdot](https://microdot.readthedocs.io/en/latest) for web services, and also provides the readout. This requires you to install the following files
- boot.py: connect to wifi on boot
- RingBuffer.py: A ringbuffer implementation.
- style.css: style file for the web server

To use wifi, you need to create `my_secrets.py` which must look like this e.g., for RedRover (which doesn't need a password):

```python
PASS=None
SSID=RedRover
```

Add a password for other networks.

### Automatic startup

To have the web page and readout run by default, the python file needs to be copied to the pico as `main.py`:

```shell
mpremote fs cp asynchio4.py :main.py
```

Micropython automatically runs the file called `main.py` when it starts.

## Other files as of 2025-9-23

- blink.py - a simple blink program that toggles the onboard LED.
- blink2.py - a simple blink program that toggles the onboard LED and the LED on the Pepper baseboard.
- findmac.py - a program that prints the MAC address of the Rpi Pico-W.
- sdtest.py - test program for the sdcard. Mounts SD card, writes a file, reads it back, and prints the contents, and then unmounts the SD card.
- setrtc.py - set the RTC on the pico using the time from an online reference.
- pepper_analyze.ipynb - Jupyter note book to analyze csv file
- muon_data_20241101_1806.csv - csv file referenced in above ipynb file.
- make_follower.py and make_leader.py: run these via mpremote to make the board a follower or leader, as appropriate, for using the boards in coincidence mode. You can also do the same on the web server from the 'technical' page.

```shell
mpremote run make_follower.py
```
