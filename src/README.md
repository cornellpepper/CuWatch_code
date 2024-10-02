# Instructions

All code assumes you have the micropy repl installed.

For the sdcard you need to install the sdcard library from micropi-libs also; see comment inline in code. Using `mpremote` the commmand is as follows.

```shell
mpremote mip install sdcard
```

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
