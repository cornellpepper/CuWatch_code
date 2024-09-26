import network
import socket
import time
from machine import Pin
from machine import RTC
import _thread
import sys

# Configure the LED pin (optional)
led = Pin("LED", Pin.OUT)
# Initial state of the LED
led.value(1)

# Shared variable
#shared_variable = {'led_state': 0}
# Lock to manage access to the shared variable
#lock = _thread.allocate_lock()

# global time string
rtc = RTC()
# Get current time from RTC in string format
def get_time():
    ts = rtc.datetime()
    ts = "{}/{}/{} {}:{}:{}".format(ts[2], ts[1], ts[0], ts[4], ts[5], ts[6])
    return ts
timestring = get_time()


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
    <p>Shared variable: {shared}</p>
    <p>Time now: {timestring}</p>
    </body>
</html>
"""

# Function to handle incoming connections and serve web pages
def web_server():
    global shared_variable
    try:
        addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
        s = socket.socket()
        s.bind(addr)
        s.listen(5)
        print('Web server running on core 1, listening on', addr)
        print(f"on thread {_thread.get_ident()}")

        while True:
            try:
                print("waiting for client...\n")
                cl, addr = s.accept()
                print('Client connected from', addr)
                request = cl.recv(1024)
                request = str(request)
                print('Request:', request)

                # LED control based on the request
                if '/?led=on' in request:
                    led.value(1)
                    # Update shared variable
                    #with lock:
                    #    shared_variable['led_state'] = 1
                if '/?led=off' in request:
                    led.value(0)
                    # Update shared variable
                    #with lock:
                    #    shared_variable['led_state'] = 0

                # Serve the HTML page with the shared variable value
                #print('LED state:', shared_variable['led_state'])
                print('Time:', timestring)
                #response = html.format(shared=shared_variable['led_state'],timestring=timestring)
                response = html.format(shared=led.value(),timestring=timestring)
                cl.send(b'HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
                cl.send(response.encode())
                cl.close()

            except Exception as e:
                print('Error with client connection:', e)
                cl.close()

    except Exception as e:
        print('Error in web server setup:', e)
        s.close()
        time.sleep(5)
        print('Restarting server...')
        web_server()  # Restart the server in case of failure

# Function to start the web server in a separate thread
def start_server_thread():
    print("Starting web server on core 1...")
    _thread.start_new_thread(web_server, ())

# Replace with your Wi-Fi credentials
ssid = 'superfrog_24'
password = 'babebeef1972'

# toggle the led
def toggle_led(val=None):
    if val is not None:
        led.value(val)
    else:
        led.value(not led.value())


# Main function that handles Wi-Fi and web server startup
def main():
    global shared_variable
    # Connect to Wi-Fi
    wlan = None
    while True:
        try:
            if wlan is None or not wlan.isconnected():
                print('Connecting to Wi-Fi...')
                wlan = connect_wifi(ssid, password)
            
            if wlan.isconnected():
                # print wifi information
                print('Network Config:', wlan.ifconfig())
                start_server_thread()  # Start the web server in a separate thread
                break  # Exit the loop once the server is running

        except Exception as e:
            print('Error with network or server:', e)
            time.sleep(5)
            print('Attempting to restart...')

    print("main continuing here")

    # Main thread can run other tasks
    while True:
        try:
            print("top of main loop")
            # Toggle the LED every 2 seconds
            time.sleep(2)
            # Update the time string
            global timestring
            timestring = get_time()
            print("it's now", timestring)
        except Exception as e:
            print('Error in main loop:', e)
            time.sleep(5)
            print('Restarting main loop...')


main()
print("after main")
