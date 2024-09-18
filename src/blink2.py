from machine import Pin
from time import sleep

led1 = Pin('LED', Pin.OUT)
led2 = Pin(15, Pin.OUT) # local LED on pepper carrier board
print('Dual blinking LED Example')

led1.value(0)
led2.value(1)

while True:
  led1.value(not led1.value())
  led2.value(not led2.value())
  sleep(0.5)
