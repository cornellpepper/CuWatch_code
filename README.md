# CuWatch_code

Code for the CuWatch PCB. The code is in MicroPython. Target is the Raspberry Pi Pico-W microcontroller.

## development instructions

Install micropython on the pico-w in the usual way (see [micropython documentation](https://docs.micropython.org/en/latest/rp2/tutorial/intro.html#rp2-intro).) Currently you can download the uf2 file for the pico-w [from this web page](https://micropython.org/download/RPI_PICO_W/). As of 11/4/2026 we are using version 1.26. To upload micropython on a Pico-W that is sitting on a Pepper baseboard, connect the Pico-w to your computer using a micro-USB cable. Hold down the reset button on the base board and the white button on the pico simultaneously. Release the reset button. The Pico-W will show up as a disk on your computer. Drag the uf2 file to that disk. The pico-w will reboot and disconnect from the computer.

## local development environment

Install `mpremote` and `mpy-cross` in your favorite local python enviromnent usins `pip`.

```sh
pip install mpremote mpy-cross
```

## How to prep a board for use in Physics 1110 at Cornell

### Clone or copy this repo to your local machine

Either download the zip file or use git to clone the local repo to your machine.

### Register the Pico-W with PhysIT

To be able to log onto the Pico-W web server, its MAC address must be registered with PhysIT. To get the mac address, plug the board into your computer and run the `findmac.py` script.

```sh
mpremote findmac.py
```

PhysIT will assign an IP address of the form v2cupepperXX.physics to the Pico-W, where XX identifies the particular Pico-W in question. Add the MAC address and corresponding number [to the table here](https://github.com/cornellpepper/CuWatch_code/blob/main/src/macs.md).

### Load the latest firmware onto the board

#### See if you need a non-standard `my_secrets.py` file

This file has the SSID and wifi password in it. The install scripts create one if none exists.
For Physics 1110, this works, since RedRover does not require a password. If you had a wifi password, you'd need a password for the wifi network too.

```text
PASS=None
SSID="RedRover"
MQTT_SERVER="pepper.physics.cornell.edu"
```

#### If you are using a MacOS or Linux

There is a shell script that should do what you want. See [the script here](https://github.com/cornellpepper/CuWatch_code/blob/main/src/install.sh).

Run as follows

```sh
sh ./install.sh
```

#### If you are using Windows

There is a powershell script that is the equivalent. Needs testing.
Question: does the shell script work with WSL in Windows?
