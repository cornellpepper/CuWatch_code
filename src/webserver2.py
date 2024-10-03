# Rui Santos & Sara Santos - Random Nerd Tutorials
# Complete project details at https://RandomNerdTutorials.com/raspberry-pi-pico-w-asynchronous-web-server-micropython/

# Import necessary modules
import network
import asyncio
import socket
import time
import random
from machine import Pin, RTC
import urequests
import ujson

# Wi-Fi credentials
ssid = 'RedRover'
password = None

# Create several LEDs
led_blink = Pin('LED', Pin.OUT)
led_control = Pin(19, Pin.OUT)

# Initialize variables
state = "OFF"
random_value = 0

# HTML template for the webpage
def webpage(random_value, state):
    html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Pico Web Server</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
        </head>
        <body>
            <h1>Raspberry Pi Pico Web Server</h1>
            <h2>Led Control</h2>
            <form action="./lighton">
                <input type="submit" value="Light on" />
            </form>
            <br>
            <form action="./lightoff">
                <input type="submit" value="Light off" />
            </form>
            <p>LED state: {state}</p>
            <h2>Fetch New Value</h2>
            <form action="./value">
                <input type="submit" value="Fetch value" />
            </form>
            <p>Fetched value: {random_value}</p>
        </body>
        </html>
        """
    return str(html)

# Init Wi-Fi Interface
def init_wifi(ssid, password):
    """connect to the designated wifi network"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    # Connect to your network
    if ( password == None ):
        wlan.connect(ssid)
    else:
        wlan.connect(ssid, password)
    # Wait for Wi-Fi connection
    connection_timeout = 10
    while connection_timeout > 0:
        print(wlan.status())
        if wlan.status() >= 3:
            break
        connection_timeout -= 1
        print('Waiting for Wi-Fi connection...')
        time.sleep(1)
    # Check if connection is successful
    if wlan.status() != 3:
        print('Failed to connect to Wi-Fi')
        return False
    else:
        print('Connection successful!')
        network_info = wlan.ifconfig()
        print('IP address:', network_info[0])
        return True
    
# 
def init_RTC():
    """set date and time in RTC. Assumes we are on the network."""
    # Get the date and time for the public IP address our node is associated with
    url = 'http://worldtimeapi.org/api/ip'
    response = urequests.get(url)
    try:
        if response.status_code != 200:
            print('Error getting time from the internet')
            return None
        data = ujson.loads(response.text)
    finally:
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
    rtc = RTC()
    rtc.datetime(dttuple)
    return data['datetime']

# Asynchronous functio to handle client's requests
async def handle_client(reader, writer):
    global state
    
    print("Client connected")
    request_line = await reader.readline()
    print('Request:', request_line)
    
    # Skip HTTP request headers
    while await reader.readline() != b"\r\n":
        pass
    
    request = str(request_line, 'utf-8').split()[1]
    print('Request:', request)
    
    # Process the request and update variables
    if request == '/lighton?':
        print('LED on')
        led_control.value(1)
        state = 'ON'
    elif request == '/lightoff?':
        print('LED off')
        led_control.value(0)
        state = 'OFF'
    elif request == '/value?':
        global random_value
        random_value = random.randint(0, 20)

    # Generate HTML response
    response = webpage(random_value, state)  

    # Send the HTTP response and close the connection
    writer.write('HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
    writer.write(response)
    await writer.drain()
    await writer.wait_closed()
    print('Client Disconnected')
    
async def blink_led():
    while True:
        led_blink.toggle()  # Toggle LED state
        await asyncio.sleep(0.5)  # Blink interval

async def main():    
    if not init_wifi(ssid, password):
        print('Exiting program.')
        return
    # Set the RTC
    print("setting RTC")
    now = init_RTC()
    print('Clock set to:', now)

    # Start the server and run the event loop
    print('Setting up server')
    server = asyncio.start_server(handle_client, "0.0.0.0", 80)
    asyncio.create_task(server)
    asyncio.create_task(blink_led())
    
    while True:
        # Add other tasks that you might need to do in the loop
        sleeptime = 30
        await asyncio.sleep(sleeptime)
        print(f'This message will be printed every {sleeptime} seconds')
        

# Create an Event Loop
loop = asyncio.get_event_loop()
# Create a task to run the main function
loop.create_task(main())

try:
    # Run the event loop indefinitely
    loop.run_forever()
except Exception as e:
    print('Error occured: ', e)
except KeyboardInterrupt:
    print('Program Interrupted by the user')
