import urequests
import ujson
import time
import machine
import network
import uos

"""Test program to set the RTC from the internet."""

# Set up the network
sta_if = network.WLAN(network.STA_IF)
sta_if.active(True)
sta_if.connect('RedRover')
while not sta_if.isconnected():
    pass

# Get the date and time for the public IP address our node is associated with
url = 'http://worldtimeapi.org/api/ip'
response = urequests.get(url)
data = ujson.loads(response.text)
print(data)
response.close()
# put current time into RTC
dttuple = (int(data['datetime'][0:4]), # year
            int(data['datetime'][5:7]), # month
            int(data['datetime'][8:10]), # day
            int(data['day_of_week']), # day of week
            int(data['datetime'][11:13]), # hour
            int(data['datetime'][14:16]), # minute
            int(data['datetime'][17:19]), # second
            0) # subsecond, not set here
rtc = machine.RTC()
rtc.datetime(dttuple)
