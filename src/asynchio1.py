from machine import ADC, Pin, RTC, idle
import asyncio
import machine
import sdcard
import time
import io
import uos
import gc
import urequests
import ujson 

import _thread
import micropython
from microdot import Microdot, Response
import network
import rp2 

import my_secrets

shutdown_request = False
app = Microdot()

def tight_loop(threshold: int, reset_threshold: int, f: io.TextIOWrapper):
    global muon_count, iteration_count, rate, waited
    print("tight loop started")
    # while True:
    #     time.sleep_us(1)
    #     iteration_count += 1
    #     pass
    led1 = Pin('LED', Pin.OUT)
    led2 = Pin(15, Pin.OUT) # local LED on pepper carrier board
    adc = ADC(0)  # Pin 26 is GP26, which is ADC0
    readout = adc.read_u16
    temperature_adc = ADC(1) #l Pin 27 is GP27, which is ADC1
    #t_readout = temperature_adc.read_u16

    tmeas = time.ticks_ms

    start_time = tmeas()
    end_time = start_time
    iteration_count = 0
    muon_count = 0
    waited = 0
    wait_counts = 0
    waited = 0
    dt = 0.
    run_start_time = start_time
    temperature_adc_value = 0
    while True:
        #wdt.feed()
        led1.toggle()
        iteration_count += 1
        if iteration_count % 1_000 == 0:
            #logger.info(f"iter {iteration_count}")
            print("iter ", iteration_count, gc.mem_free())
            gc.collect()
            #f.flush()
            #uos.sync()
        adc_value = readout()  # Read the ADC value (0 - 65535)
        #print(adc_value)
        if adc_value > threshold:
            # Get the current time in milliseconds again
            end_time = tmeas()
            muon_count += 1
            # print out when muon_count is a multiple of 10
            if muon_count % 50 == 0:
                led2.off()
                rate = 1000.*muon_count/time.ticks_diff(end_time, run_start_time)
                print(f"#: {muon_count}, {rate:.1f} Hz, {gc.mem_free()} free")
                #logger.info(f"#: {muon_count}, {rate:.1f} Hz, {gc.mem_free()} free")
                #gc.collect()
            led2.on()

            wait_counts = 100
            # wait to drop beneath reset threshold
            # time.sleep_us(3)
            while readout() > reset_threshold:
                wait_counts = wait_counts - 1
                time.sleep_us(3)
                if wait_counts == 0:
                    waited += 1 
                    #logger.warning(f"waited too long, adc value {readout()}")
                    break
                led1.toggle()
            # Calculate elapsed time in milliseconds
            dt = time.ticks_diff(end_time,start_time) # what about wraparound
            temperature_adc_value = temperature_adc.read_u16()
            start_time = end_time
            # write to the SD card
            f.write(f"{muon_count}, {adc_value}, {temperature_adc_value}, {dt}, {end_time}, {wait_counts}\n")
            led2.off()
        await time.sleep_ms(0)
        #machine.idle()
        if shutdown_request:
            print("tight loop shutdown")
            break
    return

# Init Wi-Fi Interface
def init_wifi(ssid, password):
    """connect to the designated wifi network"""
    wlan = network.WLAN(network.STA_IF)
    wlan.config(pm = 0xa11140 ) # set to no sleep mode
    rp2.country("US") # set country code
    wlan.active(True)
    # Connect to your network
    if password is None:
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

@micropython.native
def calibrate_average_rms(n: int) -> tuple:
    """calibrate the threshold value by taking the average of n samples. Assumes no muons are present"""
    led2 = Pin(15, Pin.OUT) # local LED on pepper carrier board
    adc = ADC(0)  # Pin 26 is GP26, which is ADC0
    sumval = 0
    sum_squared = 0
    for _ in range(n):
        value = adc.read_u16()
        sumval += value
        sum_squared += value ** 2
        led2.toggle()
        time.sleep_ms(25) # wait 
    mean = sumval / n
    variance = (sum_squared / n) - (mean ** 2)
    standard_deviation = variance ** 0.5
    led2.value(0)
    return mean, standard_deviation

# Define SPI pins -- see schematic for Pepper V2 board
def init_sdcard():
# Define SPI pins -- see schematic for Pepper V2 board
    spi = machine.SPI(0, sck=machine.Pin(2), mosi=machine.Pin(3), miso=machine.Pin(0))
    cs = machine.Pin(1, machine.Pin.OUT)  # Chip select pin

    # Initialize SD card
    sd = sdcard.SDCard(spi, cs)

    # Mount the SD card using the uos module
    vfs = uos.VfsFat(sd)
    uos.mount(vfs, "/sd")

    # List the contents of the SD card
    print("Filesystem mounted at /sd")

    return sd

def unmount_sdcard():
    uos.sync()
    uos.umount("/sd")
    print("SD card unmounted.")

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

def init_file(baseline, rms, threshold, reset_threshold, now) -> io.TextIOWrapper:
    """ open file for writing, with date and time in the filename """
    now2 = time.localtime()
    year = now2[0]
    month = now2[1]
    day = now2[2]
    hour = now2[3]
    minute = now2[4]
    suffix = f"{year}{month:02d}{day:02d}_{hour:02d}{minute:02d}"
    # data file
    filename = f"/sd/muon_data_{suffix}.csv"
    f = open(filename, "w", buffering=10240, encoding='utf-8')
    f.write("baseline, stddev, threshold, reset_threshold, run_start_time\n")
    f.write(f"{baseline:.1f}, {rms:.1f}, {threshold}, {reset_threshold}, {now}\n")
    f.write("Muon Count,ADC,temperature_ADC,dt,t,t_wait\n")
    return f

# Set default content type
Response.default_content_type = 'text/html'

# Main route that serves the form and the time display, plus the global variables
@app.route('/', methods=['GET'])
def index(request):
    # Use string concatenation instead of f-strings
    html = """
    <html>
        <head>
            <title>CuWatch</title>
            <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css">
            <script>
                function displayTime() {
                    let now = new Date();
                    document.getElementById('time').innerHTML = now.toLocaleTimeString();
                }
                setInterval(displayTime, 1000);  // Update time every second
            </script>
        </head>
        <body class="bg-light">
            <div class="container">
                <h1 class="my-4 text-center">CuWatch Status and Configuration</h1>
                
                <!-- Display global variables in a Bootstrap table -->
                <table class="table table-striped table-bordered">
                    <thead class="thead-dark">
                        <tr>
                            <th>Variable</th>
                            <th>Value</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>Rate (Hz)</td>
                            <td>""" + str(rate) + """</td>
                        </tr>
                        <tr>
                            <td>Muon Count</td>
                            <td>""" + str(muon_count) + """</td>
                        </tr>
                        <tr>
                            <td>Iteration Count</td>
                            <td>""" + str(iteration_count) + """</td>
                        </tr>
                        <tr>
                            <td>Threshold</td>
                            <td>""" + str(threshold) + """</td>
                        </tr>
                    </tbody>
                </table>
                
                <h3 class="my-4 text-center">Update Threshold Value</h3>
                <form action="/submit" method="POST" class="mb-4">
                    <div class="form-group">
                        <label for="threshold">Threshold (int):</label>
                        <input type="text" id="threshold" name="threshold" class="form-control" required>
                    </div>
                    <button type="submit" class="btn btn-primary btn-block">Submit</button>
                </form>

                <h3 class="my-4">Current Time:</h3>
                <p>Time: <span id="time" class="font-weight-bold"></span></p>
            </div>

            <footer class="text-center mt-5">
                <p class="text-muted">Powered by MicroPython and Microdot</p>
            </footer>
        </body>
    </html>
    """
    # Return HTML response with proper Content-Type
    return Response(body=html)

# Route to handle form submissions and update the threshold
@app.route('/submit', methods=['POST'])
def submit(request):
    global threshold  # Use the global threshold variable
    try:
        # Get the new threshold value from the form
        threshold = int(request.form['threshold'])
        print("threshold set to", threshold)
        # Redirect back to the main page to display updated values
        return index(request)
    except ValueError:
        return 'Invalid input. Please enter a valid floating point number.', 400

##################################################################    
# these variables are used for communication between web server
# and readout thread
shutdown_request = False
muon_count = 0
iteration_count = 0
rate = 0.
waited = 0
##################################################################

##################################################################

print("wifi init....")
if not init_wifi(my_secrets.SSID, my_secrets.PASS):
    print("Couldn't initialize wifi")
    time.sleep(99)

now = init_RTC()
print(f"current time is {now}")

baseline, rms = calibrate_average_rms(500)

threshold = round(baseline + 200.)
reset_threshold = round(baseline + 50.)
print(f"baseline: {baseline}, threshold: {threshold}, reset_threshold: {reset_threshold}")

init_sdcard()

f = init_file(baseline, rms, threshold, reset_threshold, now)



async def main():
    global muon_count, iteration_count, rate, waited
    server = asyncio.create_task(app.start_server(port=80, debug=True))
    #tight_loop(threshold, reset_threshold, f)
    print("tight loop started")
    # while True:
    #     time.sleep_us(1)
    #     iteration_count += 1
    #     pass
    led1 = Pin('LED', Pin.OUT)
    led2 = Pin(15, Pin.OUT) # local LED on pepper carrier board
    adc = ADC(0)  # Pin 26 is GP26, which is ADC0
    readout = adc.read_u16
    temperature_adc = ADC(1) #l Pin 27 is GP27, which is ADC1
    #t_readout = temperature_adc.read_u16

    tmeas = time.ticks_ms

    start_time = tmeas()
    end_time = start_time
    iteration_count = 0
    muon_count = 0
    waited = 0
    wait_counts = 0
    waited = 0
    dt = 0.
    run_start_time = start_time
    temperature_adc_value = 0
    while True:
        #wdt.feed()
        led1.toggle()
        iteration_count += 1
        if iteration_count % 50_000 == 0:
            #logger.info(f"iter {iteration_count}")
            print("iter ", iteration_count, gc.mem_free())
            gc.collect()
            #f.flush()
            #uos.sync()
        adc_value = readout()  # Read the ADC value (0 - 65535)
        #print(adc_value)
        if adc_value > threshold:
            # Get the current time in milliseconds again
            end_time = tmeas()
            muon_count += 1
            # print out when muon_count is a multiple of 10
            if muon_count % 50 == 0:
                led2.off()
                rate = 1000.*muon_count/time.ticks_diff(end_time, run_start_time)
                print(f"#: {muon_count}, {rate:.1f} Hz, {gc.mem_free()} free")
                #logger.info(f"#: {muon_count}, {rate:.1f} Hz, {gc.mem_free()} free")
                #gc.collect()
            led2.on()

            wait_counts = 100
            # wait to drop beneath reset threshold
            # time.sleep_us(3)
            while readout() > reset_threshold:
                wait_counts = wait_counts - 1
                time.sleep_us(3)
                if wait_counts == 0:
                    waited += 1 
                    #logger.warning(f"waited too long, adc value {readout()}")
                    break
                led1.toggle()
            # Calculate elapsed time in milliseconds
            dt = time.ticks_diff(end_time,start_time) # what about wraparound
            temperature_adc_value = temperature_adc.read_u16()
            start_time = end_time
            # write to the SD card
            f.write(f"{muon_count}, {adc_value}, {temperature_adc_value}, {dt}, {end_time}, {wait_counts}\n")
            led2.off()
        await asyncio.sleep_ms(0)
        #machine.idle()
        if shutdown_request:
            print("tight loop shutdown")
            break

    await server

try: 
    asyncio.run(main())
except KeyboardInterrupt:
    print("keyboard interrupt")
    shutdown_request = True
    time.sleep(1)
    f.close()
    unmount_sdcard()
    print("done")
except Exception as e:
    print("exception ", e)
    shutdown_request = True
    time.sleep(1)
    f.close()
    unmount_sdcard()
    print("done")
#app.run(debug=True, port=80)
