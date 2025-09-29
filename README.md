# CuWatch_code
Code for the CuWatch PCB. The code is in MicroPython. Target is the Raspberry Pi Pico-W microcontroller.

## development instructions
Install micropython on the pico in the usual way (see [micropython documentation](https://docs.micropython.org/en/latest/rp2/tutorial/intro.html#rp2-intro).)

## local development environment
Install `mpremote` and `mpy-cross` in your favorite local python enviromnent usins `pip`.

```sh
pip install mpremove mpy-cross
```

## how to load code into the microcontroller

### If you are using a MacOS or Linux, there is a shell script that should do what you want. See [the script here](https://github.com/cornellpepper/CuWatch_code/blob/main/src/install.sh).

Run as follows
```sh
sh ./install.sh
```

### if you are using Windows
there is a largely untested all-python version on the install script called `install.py`. There is also a powershell script that is totall untested (and written by ChatGPT).
