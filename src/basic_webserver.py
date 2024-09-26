import network
import socket
import time
from machine import Pin

# Configure the LED pin (optional)
led = Pin("LED", Pin.OUT)
led.value(1)

# Function to connect to Wi-Fi
def connect_wifi(ssid, password=None):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        print('Connecting to network...')
        if password is None:
            print("connecting to open network")
            wlan.connect(ssid)
        else:
            print("connecting to password protected network")
            wlan.connect(ssid, password)
        retries = 30  # Set a retry limit
        while not wlan.isconnected() and retries > 0:
            time.sleep(1)
            print('Retrying...')
            retries -= 1

    if wlan.isconnected():
        print('Network Config:', wlan.ifconfig())
    else:
        print('Failed to connect to Wi-Fi')
    
    return wlan

# HTML content to serve
html = """<!DOCTYPE html>
<html>
    <head> <title>Pico W Web Server</title> </head>
    <body> <h1>Hello from Pico W!</h1>
    <p>LED Control:</p>
    <form action="/" method="get">
        <button name="led" value="on" type="submit">Turn LED On</button>
        <button name="led" value="off" type="submit">Turn LED Off</button>
    </form>
    </body>
</html>
"""

# Function to handle incoming connections and serve web pages
def web_server():
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.bind(addr)
    s.listen(1)
    print('Listening on', addr)

    while True:
        cl, addr = s.accept()
        print('Client connected from', addr)
        request = cl.recv(1024)
        request = str(request)
        print('Request:', request)

        # LED control based on the request
        if '/?led=on' in request:
            led.value(1)
        if '/?led=off' in request:
            led.value(0)

        # Serve the HTML page
        cl.send(b'HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
        cl.send(html.encode())
        cl.close()

# Replace with your Wi-Fi credentials
ssid = 'RedRover'
password = None

# Connect to Wi-Fi and start the web server
wlan = connect_wifi(ssid, password)
web_server()
