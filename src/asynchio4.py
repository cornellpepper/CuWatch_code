from machine import ADC, Pin, RTC, idle
import asyncio
import machine
import sdcard
import time
import io
import uos as os
import gc
import urequests
import ujson as json

import micropython
from microdot import Microdot, Response
import network
import rp2 

import my_secrets
import RingBuffer


shutdown_request = False
app = Microdot()

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
    response = urequests.get(url)
    try:
        if response.status_code != 200:
            print('Error getting time from the internet')
            return None
        data = json.loads(response.text)
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

                // Fetch updated rate, muon_count, iteration_count every 30 seconds
                function fetchData() {
                    fetch('/data')
                        .then(response => response.json())
                        .then(data => {
                            document.getElementById('rate').innerHTML = data.rate;
                            document.getElementById('muon_count').innerHTML = data.muon_count;
                            document.getElementById('iteration_count').innerHTML = data.iteration_count;
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


                setInterval(fetchData, 30000);  // Update every 30 seconds
            </script>
        </head>
        <body class="bg-light">
            <div class="container">
                <h1 class="my-4 text-center">CuWatch Status and Configuration</h1>
                <p id="time"></p>
                <div class="btn-group" role="group" aria-label="Basic example">
                    <button type="button" class="btn btn-primary" onclick="window.location.href='/download'">Download data files</button>
                    <button type="button" class="btn btn-secondary" onclick="invokeMicrocontrollerMethod()">Stop Run</button>
                </div>
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
                            <td>Iteration Count</td>
                            <td id="iteration_count">""" + str(iteration_count) + """</td>
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
                <canvas id="rateChart" width="400" height="200"></canvas>
                
                <h3 class="my-4 text-center">Update Threshold Value</h3>
                <form action="/submit" method="POST" class="mb-4" onsubmit="saveGraphData(rateChart)">
                    <div class="form-group">
                        <label for="threshold">Threshold (integer):</label>
                        <input type="number" id="threshold" name="threshold" class="form-control" required>
                    </div>
                    <button type="submit" class="btn btn-primary btn-block">Submit</button>
                </form>

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
    global rate, muon_count, iteration_count
    # Return the current rate, muon_count, and iteration_count as JSON
    return Response(body=json.dumps({
        'rate': round(rate,1),
        'muon_count': muon_count,
        'iteration_count': iteration_count,
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

# Helper function to get file modification time
@micropython.native
def get_file_mtime(filepath):
    try:
        # Use os.stat() to get file metadata and extract the modification time
        stat = os.stat(filepath)
        return stat[8]  # `st_mtime` is the 9th element in the tuple (index 8)
    except:
        return 0  # If it fails, return 0 as a default


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
    print("in download_page: this much memory free after gc: ", gc.mem_free())

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
        </head>
        <body class="bg-light">
            <div class="container">
                <h1 class="my-4 text-center">Download CSV Files</h1>
                <div class="btn-group" role="group" aria-label="Basic example">
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
##################################################################

##################################################################

print("wifi init....")
if not init_wifi(my_secrets.SSID, my_secrets.PASS):
    print("Couldn't initialize wifi")
    while True:
        led1.toggle()
        time.sleep(0.5)
        led2.toggle()
        time.sleep(0.1)
        led2.toggle()
        time.sleep(0.1)

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

    dts = RingBuffer.RingBuffer(50)
    while True:
        #wdt.feed()
        led1.toggle()
        iteration_count += 1
        if iteration_count % 50_000 == 0:
            rate = 1000./dts.calculate_average()
            print(f"iter {iteration_count}, # {muon_count}, {rate:.1f} Hz, {gc.mem_free()} free")
        if iteration_count % 1_000_000 == 0:
            print("flush file, iter ", iteration_count, gc.mem_free())
            f.flush()
            os.sync()
            gc.collect()

        adc_value = readout()  # Read the ADC value (0 - 65535)
        #print(adc_value)
        if adc_value > threshold:
            # Get the current time in milliseconds again
            end_time = tmeas()
            muon_count += 1

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
            dts.append(dt)
            temperature_adc_value = temperature_adc.read_u16()
            start_time = end_time
            # write to the SD card
            f.write(f"{muon_count}, {adc_value}, {temperature_adc_value}, {dt}, {end_time}, {wait_counts}\n")
            led2.off()
        await asyncio.sleep_ms(0) # this yields to the web server running in the other thread
        #machine.idle()
        if shutdown_request:
            print("tight loop shutdown")
            raise KeyboardInterrupt
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
