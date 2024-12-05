from machine import ADC, Pin, RTC
import asyncio
import machine
import sdcard
import time
import io
import uos as os
import gc
import urequests
import ujson as json

from micropython import const
from microdot import Microdot, Response
import network
import rp2 

import my_secrets
import RingBuffer


shutdown_request = False
app = Microdot()


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
    vfs = os.VfsFat(sd)
    os.mount(vfs, "/sd")

    # List the contents of the SD card
    print("Filesystem mounted at /sd")

    return sd

def unmount_sdcard():
    os.sync()
    os.umount("/sd")
    print("SD card unmounted.")

def init_RTC():
    """set date and time in RTC. Assumes we are on the network."""
    # Get the date and time for the public IP address our node is associated with
    url = 'http://worldtimeapi.org/api/ip'
    max_retries = const(3)
    for _ in range(max_retries):
        response = urequests.get(url)
        try:
            if response.status_code == 200:
                rtc_time_data = json.loads(response.text)
                break
            else:
                print(f'Error getting time from the internet: {response.status_code}')
        finally:
            response.close()
        time.sleep(1)  # Wait for 1 second before retrying
    else:
        print('Failed to get time from the internet after 3 attempts')
        return None
    # put current time into RTC
    dttuple = (int(rtc_time_data['datetime'][0:4]), # year
                int(rtc_time_data['datetime'][5:7]), # month
                int(rtc_time_data['datetime'][8:10]), # day
                int(rtc_time_data['day_of_week']), # day of week
                int(rtc_time_data['datetime'][11:13]), # hour
                int(rtc_time_data['datetime'][14:16]), # minute
                int(rtc_time_data['datetime'][17:19]), # second
                0) # subsecond, not set here
    rtc = RTC()
    rtc.datetime(dttuple)
    return rtc_time_data['datetime']

def init_file(baseline, rms, threshold, reset_threshold, now, is_leader) -> io.TextIOWrapper:
    """ open file for writing, with date and time in the filename. write metadata. return filehandle """
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
    f.write("baseline,stddev,threshold,reset_threshold,run_start_time,is_leader\n")
    if is_leader:
        leader = 1
    else:
        leader = 0
    f.write(f"{baseline:.1f}, {rms:.1f}, {threshold}, {reset_threshold}, {now}, {leader}\n")
    f.write("Muon Count,ADC,temperature_ADC,dt,t,t_wait,coinc\n")
    return f



# Set default content type
Response.default_content_type = 'text/html'

# Path to the SD card directory where CSV files are located
SD_DIRECTORY = '/sd'

## Main route that serves the form, graph, and global variables
@app.route('/', methods=['GET'])
def index(request):
    html = """
    <!doctype html>
    <html>
        <head>
            <title>CuWatch</title>
            <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css">
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
            <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns"></script>  <!-- Include date adapter -->
            <script>
                function displayTime() {
                    let now = new Date();
                    document.getElementById('time').innerHTML = now.toLocaleTimeString();
                }
                setInterval(displayTime, 1000);  // Update time every second

                // Function to load graph data from local storage
                function loadGraphData(chart) {
                    const savedLabels = JSON.parse(localStorage.getItem('rateLabels'));
                    const savedData = JSON.parse(localStorage.getItem('rateData'));
                    if (savedLabels && savedData) {
                        chart.data.labels = savedLabels;
                        chart.data.datasets[0].data = savedData;
                        chart.update();
                    }
                }

                // Function to save graph data to local storage
                function saveGraphData(chart) {
                    localStorage.setItem('rateLabels', JSON.stringify(chart.data.labels));
                    localStorage.setItem('rateData', JSON.stringify(chart.data.datasets[0].data));
                }

                // Initialize chart for rate vs. time
                let rateChart;
                window.onload = function() {
                    const ctx = document.getElementById('rateChart').getContext('2d');
                    rateChart = new Chart(ctx, {
                        type: 'line',
                        data: {
                            labels: [],  // Time labels
                            datasets: [{
                                label: 'Rate vs Time',
                                data: [],
                                borderColor: 'rgba(75, 192, 192, 1)',
                                borderWidth: 2,
                                fill: false
                            }]
                        },
                        options: {
                            responsive: true,  // Make the chart responsive
                            maintainAspectRatio: true,  // Allow the chart to adjust its aspect ratio
                            layout: {
                                padding: {
                                    bottom: 30  // Add padding to the bottom of the chart
                                }
                            },
                            scales: {
                                x: {
                                    type: 'time',  // Use time scale
                                    time: {
                                        unit: 'second'
                                    },
                                    ticks: {
                                        source: 'auto'
                                    },
                                    min: function () {
                                        // Limit to last 1 hour
                                        const now = new Date();
                                        return new Date(now.getTime() - 60 * 60 * 1000); // 1 hour ago
                                    }
                                },
                                y: {
                                    beginAtZero: true
                                }
                            }
                        }
                    });

                    // Load graph data from local storage after initializing the chart
                    loadGraphData(rateChart);
                }

                // Function to fetch historical data from the server
                function fetchHistoricalData() {
                    fetch('/refresh_data')
                        .then(response => response.json())
                        .then(data => {
                            // Update chart with historical data
                            const now = new Date();

                            // Clear existing data
                            rateChart.data.labels = [];
                            rateChart.data.datasets[0].data = [];

                            // Add historical data to the chart
                            data.forEach((rate, index) => {
                                // Calculate the timestamp for each data point
                                const timestamp = new Date(now.getTime() - index * 60 * 1000); // 1 minute apart
                                rateChart.data.labels.unshift(timestamp); // Add the timestamp
                                rateChart.data.datasets[0].data.unshift(rate); // Add the rate
                            });

                            // Update the chart
                            rateChart.update();

                            // Save graph data to local storage
                            saveGraphData(rateChart);
                        })
                        .catch(error => {
                            console.error('Error fetching historical data:', error);
                        });
                }


                // Fetch updated rate, muon_count, iteration_count every 30 seconds
                function fetchData() {
                    fetch('/data')
                        .then(response => response.json())
                        .then(data => {
                            document.getElementById('rate').innerHTML = data.rate;
                            document.getElementById('muon_count').innerHTML = data.muon_count;
                            document.getElementById('reset_threshold').innerHTML = data.reset_threshold;
                            document.getElementById('threshold').innerHTML = data.threshold;

                            // Add new data point to the chart
                            const now = new Date();
                            rateChart.data.labels.push(now);
                            rateChart.data.datasets[0].data.push(data.rate);

                            // Remove data older than 1 hour
                            const limit = new Date(now.getTime() - 60 * 60 * 1000); // 1 hour ago
                            while (rateChart.data.labels.length > 0 && rateChart.data.labels[0] < limit) {
                                rateChart.data.labels.shift();  // Remove old labels
                                rateChart.data.datasets[0].data.shift();  // Remove corresponding data
                            }

                            // Update the chart and save it to local storage
                            rateChart.update();
                            saveGraphData(rateChart);
                        });
                }
                // Function to handle button click to invoke a method on the microcontroller
                function invokeMicrocontrollerMethod() {
                    fetch('/request-shutdown', { method: 'POST' })
                        .then(response => response.json())
                        .then(data => {
                            console.log('Method invoked:', data);
                        })
                        .catch(error => {
                            console.error('Error invoking method:', error);
                        });
                }
                function updateThreshold() {
                    // Retrieve the new threshold value from the input field
                    const newThreshold = document.getElementById('thresholdInput').value;

                    // Validate the input
                    if (newThreshold === '') {
                        alert('Please enter a valid threshold.');
                        return;
                    }

                    // Create an XMLHttpRequest object
                    const xhr = new XMLHttpRequest();
                    xhr.open('POST', '/submit', true);
                    xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');

                    // Define a callback function to handle the server's response
                    xhr.onreadystatechange = function() {
                        if (xhr.readyState === XMLHttpRequest.DONE) {
                            if (xhr.status === 200) {
                                console.log('Threshold updated successfully!');
                            } else {
                                alert('Failed to update threshold.');
                            }
                        }
                    };

                    // Send the request with the threshold data
                    xhr.send('threshold=' + encodeURIComponent(newThreshold));
                }


                setInterval(fetchData, 30000);  // Update every 30 seconds

                // Reload historical data when the window gains focus
                window.addEventListener('focus', () => {
                    console.log('Window focused, reloading historical data...');
                    fetchHistoricalData(); // Fetch historical data from the server
                });

            </script>
            <style>
                body {
                    display: block;
                }
                .sidebar {
                    width: 250px;
                    height: 100vh;
                    position: fixed;
                    top: 0;
                    left: 0;
                    background-color: #f8f9fa;
                    padding-top: 20px;
                }
                .content {
                    margin-left: 250px;
                    padding: 20px;
                    width: calc(100% - 250px);
                }
                footer {
                    position: fixed;
                    bottom: 0;
                    width: 100%;
                    background-color: #f8f9fa;
                    padding: 10px 0;
                }
                #rateChart {
                    width: 100%;  /* Make the canvas take the full width of its container */
                    height: auto; /* Maintain the aspect ratio */
                }
            </style>
        </head>
        <body class="bg-light">
            <div class="sidebar">
                <h2 class="text-center">CuWatch</h2>
                <ul class="nav flex-column">
                    <li class="nav-item">
                        <a class="nav-link active" href="/">Home</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/download">Download Data</a>
                    </li>
                    <li class="nav-item">
                        <button class="btn btn-secondary" onclick="invokeMicrocontrollerMethod()">Stop Run</button>
                    </li>
                    <li class="nav-item">
                        <input type="number" id="thresholdInput" class="form-control" placeholder="Enter new threshold">
                        <button class="btn btn-primary mt-2" onclick="updateThreshold()">Update Threshold</button>
                    </li>
                </ul>
                <p id="time" class="text-center mt-4"></p>
            </div>
            <div class="content">
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
                            <td id="rate">""" + "{:.1f}".format(rate) + """</td>
                        </tr>
                        <tr>
                            <td>Muon Count</td>
                            <td id="muon_count">""" + str(muon_count) + """</td>
                        </tr>
                        <tr>
                            <td>Threshold (ADC counts)</td>
                            <td id="threshold">""" + str(threshold) + """</td>
                        </tr>
                        <tr>
                            <td>Reset threshold (ADC counts)</td>
                            <td id="reset_threshold">""" + str(reset_threshold) + """</td>
                        </tr>
                    </tbody>
                </table>

                <!-- Chart.js graph for Rate vs Time -->
                <h3 class="my-4 text-center">Rate vs Time</h3>
                <canvas id="rateChart"></canvas>
                
            </div>

            <footer class="text-center mt-5">
                <p class="text-muted">Powered by MicroPython and Microdot</p>
            </footer>
        </body>
    </html>
    """
    return Response(body=html, headers={'Content-Type': 'text/html'})

# API route to return dynamic data (rate, muon_count, iteration_count)
@app.route('/data', methods=['GET'])
def data(request):
    """Return the current rate, muon_count, and iteration_count as JSON"""
    return Response(body=json.dumps({
        'rate': round(rate,1),
        'muon_count': muon_count,
        'threshold': threshold,
        'reset_threshold': reset_threshold
    }), headers={'Content-Type': 'application/json'})

# Route to handle form submissions and update the threshold
@app.route('/submit', methods=['POST'])
def submit(request):
    global threshold
    try:
        # Update the threshold
        threshold = int(request.form['threshold'])  # Convert to integer
        
        # Redirect to the main page to avoid form resubmission prompt
        return Response.redirect('/')
    except ValueError:
        return 'Invalid input. Please enter a valid integer.', 400

# Route to handle shutdown request
@app.route('/request-shutdown', methods=['POST'])
def request_shutdown(request):
    global shutdown_request
    shutdown_request = True
    return {"status": "Shutdown request sent"}


# Helper function to concatenate paths (since os.path.join is not available)
@micropython.native
def join_path(directory, filename):
    if directory.endswith('/'):
        return directory + filename
    else:
        return directory + '/' + filename


# Route to list and allow downloads of CSV files from the /sd directory
@app.route('/download', methods=['GET'])
def download_page(request):
    files = []
    file_limit = 50
    filecount = 0

    # Get list of .csv files in the /sd directory
    try:
        if os.stat(SD_DIRECTORY):  # Check if directory exists
            files = [f for f in os.listdir(SD_DIRECTORY) if f.endswith('.csv')]
            filecount = len(files)
            # limit to last 50 files. These appear to be the most recent ones
            files = files[-file_limit:]
        # Sort files by modification time (most recent first). This does not work
        # as it requires too much memory when the list of files gets long
        #files = sorted(files, key=lambda x: get_file_mtime(join_path(SD_DIRECTORY, x)), reverse=True)
    except OSError:
        files = []  # Handle case where SD card is not mounted or directory doesn't exist
    # 
    gc.collect()

    # Generate HTML for displaying the list of files with download links
    file_list_html = '<ul class="list-group">'
    for file in files[::-1]: # reverse the list to show most recent first
        file_list_html += f'<li class="list-group-item"><a href="/download_file?file={file}">{file}</a></li>'
    file_list_html += "</ul>"

    html = f"""
    <!doctype html>
    <html>
        <head>
            <title>Download CSV Files</title>
            <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css">
            <link rel="stylesheet" href="/styles.css">
        </head>
        <body class="bg-light">
            <div class="container">
                <h1 class="my-4 text-center">Download CSV Files</h1>
                <div class="btn-group" role="group" aria-label="Navigation Link">
                    <button type="button" class="btn btn-primary" onclick="window.location.href='/'">Return home</button>
                </div>

                <h3 class="my-4 text-center">Total number of files (showing {file_limit}): {filecount}</h3>
                {file_list_html}
                <a href="/">Back to Home</a>
            </div>
        </body>
    </html>
    """
    return Response(body=html, headers={'Content-Type': 'text/html'})

# Helper function to stream file content in chunks
def file_stream_generator(file_path, chunk_size=512):
    try:
        with open(file_path, 'r') as f:
            while True:
                data = f.read(chunk_size)
                if not data:
                    break
                yield data
    except OSError:
        yield ''  # If file cannot be read, return empty content
# Route to serve a specific CSV file for download via streaming
@app.route('/download_file', methods=['GET'])
def download_file(request):
    file_name = request.args.get('file')
    file_path = join_path(SD_DIRECTORY, file_name)
    try:
        if os.stat(file_path) and file_name.endswith('.csv'):
            # Check if the file has non-zero length
            if os.stat(file_path)[6] > 0:  # `st_size` is the 7th element in the tuple (index 6)
                # Stream the file content using the generator function
                return Response(body=file_stream_generator(file_path), headers={
                    'Content-Type': 'text/csv',
                    'Content-Disposition': f'attachment; filename="{file_name}"'
                })
            else:
                return Response('File is empty', 400)
    except OSError:
        return Response('File not found', 404)

@app.route('/technical')
def technical_page(request):
    html = f"""
    <!doctype html>
    <html>
        <head>
            <title>CuWatch Technical Information
            </title>
            <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css">
            <link rel="stylesheet" href="/styles.css">
        </head>
        <body class="bg-light">
            <div class="container">
            <h1 class="my-4 text-center">CuWatch Technical Information</h1>
            <table class="table table-striped table-bordered">
                <thead class="thead-dark">
                <tr>
                    <th>Parameter</th>
                    <th>Value</th>
                </tr>
                </thead>
                <tbody>
                <tr>
                    <td>Loop time (ms) </td>
                    <td>{avg_time}</td>
                </tr>
                <tr>
                    <td>Waited</td>
                    <td>{waited}</td>
                </tr>
                <tr>
                    <td>Leader</td>
                    <td>{is_leader}</td>
                </tr>
                <tr>
                    <td>Iteration</td>
                    <td>{iteration_count}</td>
                </tr>
                </tbody>
            </table>
            <a href="/">Back to Home</a>
            </div>
        </body>
    </html>
    """
    return Response(body=html, headers={'Content-Type': 'text/html'})

@app.route('/styles.css')
def stylesheet(request):
    try:
        with open('styles.css', 'r') as f:
            css_content = f.read()
        return Response(body=css_content, headers={'Content-Type': 'text/css'})
    except OSError:
        return Response('/* Stylesheet not found */', headers={'Content-Type': 'text/css'})

def usr_switch_pressed(pin):
    """interrupt handler for the user switch"""
    global switch_pressed
    if pin.value() == 1:
        switch_pressed = True

@app.route('/refresh_data', methods=['GET'])
def refresh_data(request):
    global rates
    if rates is not None:
        data = list(rates.get())[::-1]
        print(data)
        return Response(body=json.dumps(data), headers={'Content-Type': 'application/json'})
    else:
        return Response(body=json.dumps([]), headers={'Content-Type': 'application/json'})

def check_leader_status():
    """check if this node is the leader or not. If the file /sd/is_secondary exists, then this is a secondary node"""
    try:
        os.stat("/sd/is_secondary")
        return False
    except OSError:
        return True

##################################################################    
# these variables are used for communication between web server
# and readout thread
shutdown_request = False
muon_count = 0
iteration_count = 0
rate = 0.
waited = 0
threshold = 0
reset_threshold = 0
is_leader = True
avg_time = 0.
rates = RingBuffer.RingBuffer(60,'f')
##################################################################

##################################################################

### SET UP GPIO PINS
# set up switch on pin 16
usr_switch = Pin(16, Pin.IN, Pin.PULL_DOWN)
switch_pressed = False
usr_switch.irq(trigger=Pin.IRQ_RISING, handler=usr_switch_pressed)

# # HV supply -- active low pin to turn off
# # the high voltage power supply
# hv_power_enable = Pin(19, Pin.OUT)
# hv_power_enable.on() # turn on the HV supply


led1 = Pin('LED', Pin.OUT)
led2 = Pin(15, Pin.OUT) # local LED on pepper carrier board

# check if the network is active. It should already be 
# set up from boot.py
wlan = network.WLAN(network.STA_IF)
if not wlan.active():
    print("Wifi is not active")
    while True:
        led1.toggle()
        time.sleep(0.5)
        led2.toggle()
        time.sleep(0.1)
        led2.toggle()
        time.sleep(0.1)

now = init_RTC()
print(f"current time is {now}")

# I think these need to set up the pins, too
adc = ADC(Pin(26))       # create ADC object on ADC pin
adc_temp = ADC(Pin(27))  # create ADC object on ADC pin

# # calibrate the threshold with HV off
# hv_power_enable.off()
# baseline, rms = calibrate_average_rms(500)

# # 100 counts correspond to roughly (100/(2^16))*3.3V = 0.005V. So 1000 counts
# # is 50 mV above threshold. the signal in Sally is about 0.5V.
# threshold = int(round(baseline + 1000.))
# reset_threshold = round(baseline + 50.)
# print(f"baseline: {baseline}, threshold: {threshold}, reset_threshold: {reset_threshold}")

# # calibrate the threshold with HV on
# hv_power_enable.on()
baseline, rms = calibrate_average_rms(500)

# 100 counts correspond to roughly (100/(2^16))*3.3V = 0.005V. So 1000 counts
# is 50 mV above threshold. the signal in Sally is about 0.5V.
threshold = int(round(baseline + 1000.))
reset_threshold = round(baseline + 50.)
print(f"baseline: {baseline}, threshold: {threshold}, reset_threshold: {reset_threshold}")




init_sdcard()

coincidence_pin = None
is_leader = check_leader_status()
if is_leader:
    coincidence_pin = Pin(14, Pin.IN)
else:
    coincidence_pin = Pin(14, Pin.OUT)
print("is_leader is ", is_leader)


f = init_file(baseline, rms, threshold, reset_threshold, now, is_leader)



async def main():
    global muon_count, iteration_count, rate, waited, switch_pressed, avg_time
    global rates
    server = asyncio.create_task(app.start_server(port=80, debug=True))
    print("tight loop started")
    l1t = led1.toggle
    l2on = led2.on
    l2off = led2.off
    adc = ADC(0)  # Pin 26 is GP26, which is ADC0. Assumption is that pins were set up earlier.
    readout = adc.read_u16
    temperature_adc = ADC(1) #l Pin 27 is GP27, which is ADC1. Same comment about pin setup.
    #t_readout = temperature_adc.read_u16

    tmeas = time.ticks_ms
    tusleep = time.sleep_us
    start_time = tmeas()
    end_time = start_time
    iteration_count = 0
    muon_count = 0
    waited = 0
    wait_counts = 0
    waited = 0
    dt = 0.
    run_start_time = start_time
    tlast = start_time
    temperature_adc_value = 0

    INNER_ITER_LIMIT = const(400_000)
    OUTER_ITER_LIMIT = const(20*INNER_ITER_LIMIT)

    dts = RingBuffer.RingBuffer(50)
    coincidence = 0
    loop_timer_time = tmeas()
    while True:
        iteration_count += 1
        if iteration_count % INNER_ITER_LIMIT == 0:
            rate = 1000./dts.calculate_average()
            tdiff = time.ticks_diff(tmeas(), loop_timer_time)
            avg_time = tdiff/INNER_ITER_LIMIT
            print(f"iter {iteration_count}, # {muon_count}, {rate:.1f} Hz, {gc.mem_free()} free, avg time {avg_time:.3f} ms")
            l1t()
            loop_timer_time = tmeas()
            # update rates ring buffer every minute
            if time.ticks_diff(loop_timer_time, tlast) >= 60000:  # 60,000 ms = 1 minute
                print("updating rates")
                rates.append(rate)
                print(rates.get())
                tlast = loop_timer_time
            if iteration_count % OUTER_ITER_LIMIT == 0:
                print("flush file, iter ", iteration_count, gc.mem_free())
                f.flush()
                os.sync()
                gc.collect()
        adc_value = readout()  # Read the ADC value (0 - 65535)
        #print(adc_value)
        if adc_value > threshold:
            l2on()
            # Get the current time in milliseconds again
            end_time = tmeas()
            muon_count += 1
            wait_counts = 150
            if not is_leader:
                coincidence_pin.value(1)
            else:
                if coincidence_pin.value() == 1:
                    coincidence = 1
                else:
                    coincidence = 0
            # wait to drop beneath reset threshold
            # time.sleep_us(3)
            while readout() > reset_threshold:
                wait_counts = wait_counts - 1
                tusleep(1)
                if is_leader and coincidence == 0: # latch value of coincidence
                    if coincidence_pin.value() == 1:
                        coincidence = 1
                if wait_counts == 0:
                    waited += 1 
                    #logger.warning(f"waited too long, adc value {readout()}")
                    break
            # Calculate elapsed time in milliseconds
            dt = time.ticks_diff(end_time,start_time) # what about wraparound
            dts.append(dt)
            temperature_adc_value = temperature_adc.read_u16()
            start_time = end_time
            # write to the SD card
            f.write(f"{muon_count}, {adc_value}, {temperature_adc_value}, {dt}, {end_time}, {wait_counts}, {coincidence}\n")
            l2off()
            if not is_leader:
                coincidence_pin.value(0)
        if iteration_count % 1_000 == 0:
            await asyncio.sleep_ms(0) # this yields to the web server running in the other thread
        if shutdown_request or switch_pressed:
            print("tight loop shutdown, waited is ", waited)
            break
    f.close()
    #await server

# start the web server and wait for exceptions to end it. 
try: 
    asyncio.run(main())
except KeyboardInterrupt:
    print("keyboard interrupt")
    try:
        f.close()
    except:
        pass
    unmount_sdcard()
    print("done")
except Exception as e:
    print("exception ", e)
    try:
        f.close()
    except:
        pass
    unmount_sdcard()
    print("done")

# just restart at the end 
machine.reset()
