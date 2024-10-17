import machine
import time
import _thread
import micropython
from microdot import Microdot #, redirect, send_file
import network
import my_secrets
#from threadsafe import ThreadSafeQueue

@micropython.native
def read_sensor():
    global v, i
    adc = machine.ADC(0)
    f = adc.read_u16
    i = 0
    while True:
        i += 1
        v = f()
        machine.idle()
        if shutdown_request:
            print("thread1 shutdown")
            break
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
    connection_timeout = 30
    print('Waiting for Wi-Fi connection ...', end="")
    cycle = [ '   ', '.  ', '.. ', '...']
    i = 0
    #led2.value(1)
    #led1.value(0)
    while connection_timeout > 0:
        if wlan.status() >= network.STAT_GOT_IP:
            break
        connection_timeout -= 1
        print(f"\b\b\b{cycle[i]}", end="")
        i = (i + 1) % 4
        time.sleep(1)
        #led1.toggle()
        #led2.toggle()
    
    print("\b\b\b   ")
    # Check if connection is successful
    if wlan.status() != network.STAT_GOT_IP:
        print('Failed to connect to Wi-Fi')
        return False
    else:
        print('Connection successful!')
        network_info = wlan.ifconfig()
        print('IP address:', network_info[0])
        return True
    

v = 0
i = 0
shutdown_request = False

html = '''<!DOCTYPE html>
<html>
    <head>
        <title>Microdot Example Page</title>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="10">
    </head>
    <body>
        <div>
            <h1>Microdot Example Page</h1>
            <p>Hello from Microdot!</p>
            <p>ADC: {v}</p>
            <p>Cnt: {i}</p>
            <p><a href="/shutdown">Click to shutdown the server</a></p>
        </div>
    </body>
</html>
'''

print("wifi init....")
if (not init_wifi(my_secrets.SSID, my_secrets.PASS) ):
    print("Couldn't initialize wifi")
    time.sleep(99)

print("start: shutdown_request = ", shutdown_request)

app = Microdot()

@app.route('/')
async def hello(request):
    repl_html = html.replace("{v}", str(v)).replace("{i}", str(i))
    return (repl_html, 200, {'Content-Type': 'text/html'})

@app.route('/shutdown')
async def shutdown(request):
    global shutdown_request
    shutdown_request = True
    print("shutting down")
    time.sleep(10)
    request.app.shutdown()
    return 'The server is shutting down...'


_thread.start_new_thread(read_sensor, ())

app.run(debug=True, port=80)
