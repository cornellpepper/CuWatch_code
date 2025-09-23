# pylint: disable=missing-function-docstring,missing-class-docstring,missing-module-docstring
# pylint: disable=too-many-locals,too-many-statements,too-many-arguments, invalid-name, global-statement
# pylint: disable=consider-using-f-string, line-too-long, unused-argument
from machine import ADC, Pin, RTC
import asyncio
import machine
import sdcard
import sys
import time
import io
import uos as os
import gc
import urequests
import ujson as json
import ntptime

from micropython import const
from microdot import Microdot, Response
import network
import rp2 

import my_secrets
import RingBuffer
import urandom


shutdown_request = False
app = Microdot()

# --- MicroPython-safe print capture for live debug log ---
try:
    import builtins as _bi  # CPython/MicroPython compatible
except ImportError:
    _bi = None

DEBUG_LOG = []
MAX_LOG_LINES = const(220)  # cap memory use

if _bi is not None and hasattr(_bi, 'print'):
    _ORIG_PRINT = _bi.print
    def _tee_print(*args, **kwargs):
        # Always call original print first
        try:
            _ORIG_PRINT(*args, **kwargs)
        finally:
            # Then capture into memory buffer
            try:
                sep = kwargs.get('sep', ' ')
                end = kwargs.get('end', '\n')
                s = sep.join([str(a) for a in args]) + end
                DEBUG_LOG.append(s)
                if len(DEBUG_LOG) > MAX_LOG_LINES:
                    del DEBUG_LOG[: len(DEBUG_LOG) - MAX_LOG_LINES]
            except Exception:
                pass
    _bi.print = _tee_print

@micropython.native
def calibrate_average_rms(n: int) -> tuple:
    """calibrate the threshold value by taking the average of n samples. Assumes no muons are present"""
    led2 = Pin(15, Pin.OUT) # local LED on pepper carrier board
    adc = ADC(0)  # Pin 26 is GP26, which is ADC0
    sumval = 0
    sum_squared = 0
    print("Calibrating with", n, "samples...")
    for _ in range(n):
        value = adc.read_u16()
        sumval += value
        sum_squared += value ** 2
        led2.toggle()
        time.sleep_ms(10) # wait 
    mean = sumval / n
    variance = (sum_squared / n) - (mean ** 2)
    standard_deviation = variance ** 0.5
    led2.value(0)
    return mean, standard_deviation


def init_sdcard():
    """ Initialize the SD card interface on the base board"""
    # Define SPI pins -- see schematic for Pepper V2 board
    spi = machine.SPI(0, sck=machine.Pin(2), mosi=machine.Pin(3), miso=machine.Pin(0))
    cs = machine.Pin(1, machine.Pin.OUT)  # Chip select pin

    # Initialize SD card
    sd = sdcard.SDCard(spi, cs)

    # Mount the SD card using the uos module
    vfs = os.VfsFat(sd)
    os.mount(vfs, SD_DIRECTORY)

    # List the contents of the SD card
    print("Filesystem mounted at /sd")

    return sd

def unmount_sdcard():
    os.sync()
    os.umount(SD_DIRECTORY)
    print("SD card unmounted.")

def init_RTC():
    """set RTC to UTC. Uses NTP and falls back to worldtimeapi.org if NTP fails"""
    import random
    server = random.choice(['0.pool.ntp.org', '1.pool.ntp.org', '2.pool.ntp.org', '3.pool.ntp.org'])
    ntptime.host = server
    ntptime.timeout = 2
    print(f"NTP host is {ntptime.host}")
    wait_time = 2
    success = False
    rtc = RTC()
    led2 = Pin(15, Pin.OUT) # local LED on pepper carrier board
    for _ in range(5):
        print("waiting for NTP time")
        try:
            led2.toggle()
            ntptime.settime()
            # if we get here, assume it succeeded (above throws exception on fail)
            print("NTP success: ", rtc.datetime())
            success = True
            break
        except OSError as e:
            print(f"NTP time setting failed. Check network connection. {e}")
        except Error as e:
            print(f"unexpected error: {e}")
        time.sleep(wait_time)
        wait_time = wait_time * 2
    if not success:
        # fall back to urequests method
        print("NTP failed, trying worldtimeapi.org")
        try:
            response = urequests.get('http://worldtimeapi.org/api/ip')
            data = response.json()
            datetime_str = data['utc_datetime']
            print("datetime_str: ", datetime_str)
            year, month, day, hour, minute, second = map(int, datetime_str.split('T')[0].split('-') + datetime_str.split('T')[1].split(':'))
            rtc.datetime((year, month, day, 0, hour, minute, second, 0))
            success = True
            print("RTC set to: ", rtc.datetime())
        except Error as e:
            print(f"Failed to set RTC time: {e}")
    
    if not success:
        print("Failed to set RTC time")
        random_hour = urandom.getrandbits(5) % 24  # Generate a random hour (0-23)
        random_minute = urandom.getrandbits(6) % 60  # Generate a random minute (0-59)
        # Set RTC to a random time on 1/1/2020
        rtc.datetime((2020, 1, 1, 0, random_hour, random_minute, 0, 0))
    return get_iso8601_timestamp()


def get_iso8601_timestamp(timezone_offset="+00:00"):
    """return RTC time as an ISO8601 string, default to UTC TZ"""
    rtc = RTC()
    dt = rtc.datetime()

    # NOTE: no microsecond support in RTC, so we use 000000
    timestamp = "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.{:06d}{}".format(
        dt[0], dt[1], dt[2], dt[4], dt[5], dt[6], 0, timezone_offset
    )

    return timestamp

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


# Streamed HTML generator for the home page (keeps memory usage low)
def _index_stream(myrate, muon_count, baseline, threshold, reset_threshold, runtime):
    yield """
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>CuWatch</title>
        <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css">
        <link rel="stylesheet" href="/styles.css">
      </head>
      <body class="bg-light">
        <div class="d-flex">
          <div class="sidebar">
            <h2 class="text-center">CuWatch</h2>
            <ul class="nav flex-column">
              <li class="nav-item"><a class="nav-link active" href="/">Home</a></li>
              <li class="nav-item"><a class="nav-link" href="/download">Download Data</a></li>
              <li class="nav-item"><a class="nav-link" href="/technical">Technical</a></li>
              <li class="nav-item"><button class="btn btn-secondary" onclick="invokeMicrocontrollerMethod()">Stop Run</button></li>
              <li class="nav-item"><button class="btn btn-secondary" onclick="restartRequest()">Restart Run</button></li>
              <li class="nav-item">
                <input type="number" id="thresholdInput" class="form-control" placeholder="Enter new threshold">
                <button class="btn btn-primary mt-2" onclick="updateThreshold()">Update Threshold</button>
              </li>
            <li class="nav-item">
                <small class="form-text text-muted mt-1">
                    Threshold should be an integer greater than the reset threshold.
                </small>
            </li>
            </ul>
            <p id="time" class="text-center mt-4"></p>
          </div>
          <div class="content">
            <h1 class="my-4 text-center">CuWatch Status and Configuration</h1>
            <table class="table table-striped table-bordered">
              <thead class="thead-dark">
                <tr><th>Variable</th><th>Value</th></tr>
              </thead>
              <tbody>
                <tr><td>Rate (Hz)</td><td id="rate">"""
    yield str(myrate)
    yield """</td></tr>
                <tr><td>Muon Count</td><td id="muon_count">"""
    yield str(muon_count)
    yield """</td></tr>
                <tr><td>Baseline (ADC counts)</td><td id="baseline">"""
    yield str(baseline)
    yield """</td></tr>
                <tr><td>Threshold (ADC counts)</td><td id="threshold">"""
    yield str(threshold)
    yield """</td></tr>
                <tr><td>Reset threshold (ADC counts)</td><td id="reset_threshold">"""
    yield str(reset_threshold)
    yield """</td></tr>
                <tr><td>Runtime (s)</td><td id="runtime">"""
    yield str(runtime)
    yield """</td></tr>
              </tbody>
            </table>
            <p id="last_updated" class="text-muted small text-right mb-0">Last updated: —</p>
            <h3 class="my-4 text-center">Rate vs Time</h3>
            <canvas id="rateChart"></canvas>
          </div>
        </div>
        <footer class="text-center mt-5"><p class="text-muted">Powered by MicroPython and Microdot</p></footer>
        <script src="/boot.js?v=1"></script>
      </body>
    </html>
    """

@app.route('/', methods=['GET'])
def index(request):
    """Main route: streamed to lower peak memory and move JS to /app.js"""
    myrate = rates.get_tail()
    if myrate is None:
        myrate = 0.
    runtime = time.time() - start_time_sec
    return Response(body=_index_stream(myrate, muon_count, baseline, threshold, reset_threshold, runtime),
                    headers={'Content-Type': 'text/html', 'Cache-Control': 'no-cache'})

@app.before_request
def _log_request(request):
    try:
        #print("REQ", request.method, request.path)
        global last_req_ms
        last_req_ms = time.ticks_ms()
    except Exception:
        pass
# API route to return dynamic data (rate, muon_count, iteration_count)
@app.route('/data', methods=['GET'])
def data(request):
    """Return the current rate, muon_count, and iteration_count as JSON"""
    myrate = rates.get_tail()
    if myrate is None:
       myrate = 0.
    runtime = time.time() - start_time_sec
    return Response(body=json.dumps({
        'rate': myrate,
        'muon_count': muon_count,
        'threshold': threshold,
        'reset_threshold': reset_threshold,
        'runtime': runtime,
        'baseline': baseline
    }), headers={'Content-Type': 'application/json'})

# Lightweight health endpoint: if this responds, the server is active
@app.route('/healthz', methods=['GET'])
def healthz(request):
    return Response(body='ok', headers={'Content-Type': 'text/plain'})

# Route to handle form submissions and update the threshold
@app.route('/submit', methods=['POST'])
def submit(request):
    global threshold
    try:
        # Update the threshold
        new_value = int(request.form['threshold'])  # Convert to integer
        if new_value < 0:
            new_value = 0
        elif new_value > 65535:
            new_value = 65535
        # make sure this is not below the reset threshold
        if new_value < reset_threshold:
            return 'New threshold cannot be below reset threshold.', 400
        threshold = new_value
        
        # Redirect to the main page to avoid form resubmission prompt
        return Response.redirect('/')
    except ValueError:
        return 'Invalid input. Please enter a valid integer.', 400

# Route to handle shutdown request
@app.route('/request-shutdown', methods=['POST'])
async def request_shutdown(request):
    global shutdown_request
    shutdown_request = True
    return {"status": "Shutdown request sent"}

# Route to handle restart request
@app.route('/request-restart', methods=['POST'])
async def request_restart(request):
    global restart_request
    restart_request = True
    # Do not call app.shutdown() here; let the main loop handle a graceful stop
    return {"status": "Reset request queued"}

# route to handle make-leader request
@app.route('/make-leader', methods=['POST'])
def make_leader(request):
    global is_leader
    secondary_marker = "is_secondary"
    if secondary_marker in os.listdir(SD_DIRECTORY):
        os.remove(join_path('/sd', secondary_marker))
        print(f"Removed {secondary_marker}")
    else:
        print(f"{secondary_marker} does not exist")

    is_leader = True
    return {"status": "Make Leader invoked"}

# route to handle make-follower request
@app.route('/make-follower', methods=['POST'])
def make_follower(request):
    global is_leader
    secondary_marker = "is_secondary"
    if secondary_marker in os.listdir(SD_DIRECTORY):
        print(f"{secondary_marker} already exists")
    else:
        with open(join_path('/sd', secondary_marker), "w") as f:
            f.write("This node is a follower")
        print(f"Created {secondary_marker}")
    is_leader = False
    return {"status": "Make Follower invoked"}

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
    FILE_LIMIT = const(30)
    filecount = 0

    # Get list of .csv files in the /sd directory
    try:
        if os.stat(SD_DIRECTORY):  # Check if directory exists
            ring = []
            # Prefer iterator on MicroPython to avoid a large list
            if hasattr(os, 'ilistdir'):
                for entry in os.ilistdir(SD_DIRECTORY):
                    try:
                        name = entry[0] if isinstance(entry, tuple) else entry
                    except Exception:
                        name = entry
                    if isinstance(name, bytes):
                        try:
                            name = name.decode()
                        except Exception:
                            name = str(name)
                    if isinstance(name, str) and name.endswith('.csv'):
                        filecount += 1
                        ring.append(name)
                        if len(ring) > FILE_LIMIT:
                            del ring[0]
            else:
                try:
                    names = os.listdir(SD_DIRECTORY)
                except Exception:
                    names = []
                for name in names:
                    if name.endswith('.csv'):
                        filecount += 1
                        ring.append(name)
                        if len(ring) > FILE_LIMIT:
                            del ring[0]
            files = ring
        # Sort files by modification time (most recent first). This does not work
        # as it requires too much memory when the list of files gets long
        #files = sorted(files, key=lambda x: get_file_mtime(join_path(SD_DIRECTORY, x)), reverse=True)
    except OSError:
        files = []  # Handle case where SD card is not mounted or directory doesn't exist
    # 
    gc.collect()

    # Stream HTML to reduce memory usage
    def _stream():
        yield "<!doctype html>\n<html>\n  <head>\n    <title>Download CSV Files</title>\n"
        yield "    <link rel=\"stylesheet\" href=\"https://maxcdn.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css\">\n"
        yield "    <link rel=\"stylesheet\" href=\"/styles.css\">\n  </head>\n  <body class=\"bg-light\">\n    <div class=\"container\">\n      <h1 class=\"my-4 text-center\">Download CSV Files</h1>\n      <div class=\"btn-group\" role=\"group\" aria-label=\"Navigation Link\">\n        <button type=\"button\" class=\"btn btn-primary\" onclick=\"window.location.href='/'\">Return home</button>\n      </div>\n"
        yield "      <h3 class=\"my-4 text-center\">Total number of files (showing %d): %d</h3>\n" % (FILE_LIMIT, filecount)
        yield "      <ul class=\"list-group\">\n"
        for fname in files[::-1]:
            yield "        <li class=\"list-group-item\"><a href=\"/download_file?file=%s\">%s</a></li>\n" % (fname, fname)
        yield "      </ul>\n      <a href=\"/\">Back to Home</a>\n    </div>\n  </body>\n</html>\n"
    return Response(body=_stream(), headers={'Content-Type': 'text/html'})

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
        st = os.stat(file_path)
        if st and file_name.endswith('.csv'): # Check if the file has non-zero length
            if st[6] > 0:  # `st_size` is the 7th element in the tuple (index 6)
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
    # Streamed version to avoid MemoryError on large f-strings
    def _stream():
        yield "<!doctype html>\n<html>\n  <head>\n    <title>CuWatch Technical Information</title>\n"
        yield "    <link rel=\"stylesheet\" href=\"https://maxcdn.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css\">\n"
        yield "    <link rel=\"stylesheet\" href=\"/styles.css\">\n"
        yield "    <script>\n"
        yield "      function displayTime(){var now=new Date();var e=document.getElementById('time'); if(e){e.textContent=now.toLocaleTimeString();}}\n"
        yield "      setInterval(displayTime,1000);\n"
        yield "      function makeLeader(){fetch('/make-leader',{method:'POST'}).then(r=>r.json()).then(_=>reloadTable()).catch(()=>{});}\n"
        yield "      function makeFollower(){fetch('/make-follower',{method:'POST'}).then(r=>r.json()).then(_=>reloadTable()).catch(()=>{});}\n"
        yield "      function reloadTable(){fetch('/technical/table').then(r=>r.text()).then(function(h){var t=document.getElementById('table-container'); if(t){t.innerHTML=h;}}).catch(()=>{});}\n"
        yield "    </script>\n  </head>\n  <body class=\"bg-light\">\n    <div class=\"d-flex\">\n      <div class=\"sidebar bg-light p-3\">\n        <h2 class=\"text-center\">CuWatch</h2>\n        <ul class=\"nav flex-column\">\n"
        yield "          <li class=\"nav-item\"><a class=\"nav-link active\" href=\"/\">Home</a></li>\n"
        yield "          <li class=\"nav-item\"><a class=\"nav-link\" href=\"/download\">Download Data</a></li>\n"
        yield "          <li class=\"nav-item\"><button class=\"btn btn-secondary my-2\" onclick=\"makeLeader()\">Make Leader</button></li>\n"
        yield "          <li class=\"nav-item\"><button class=\"btn btn-secondary my-2\" onclick=\"makeFollower()\">Make Follower</button></li>\n"
        yield "        </ul>\n        <div class=\"static-text bg-secondary text-white p-3 rounded mt-3\">\n          <p>Leader and follower changes take effect on next new run.</p>\n        </div>\n        <p id=\"time\" class=\"text-center mt-4\"></p>\n      </div>\n      <div class=\"content flex-grow-1 p-3\">\n        <h1 class=\"my-4 text-center\">CuWatch Technical Information</h1>\n        <div id=\"table-container\">\n"
        try:
            yield generate_table()
        except Exception:
            yield "<p>Error loading table.</p>"
        yield "        </div>\n      </div>\n    </div>\n  </body>\n</html>\n"
    return Response(body=_stream(), headers={'Content-Type': 'text/html'})

def generate_table():
    return f"""
    <table class="table table-striped table-bordered">
        <thead class="thead-dark">
            <tr>
                <th>Parameter</th>
                <th>Value</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>Loop time (ms)</td>
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
                <td>Iteration Count</td>
                <td>{iteration_count}</td>
            </tr>
        </tbody>
    </table>
    """

@app.route('/technical/table')
def technical_table(request):
    return Response(generate_table(), headers={'Content-Type': 'text/html'})


@app.route('/styles.css')
def stylesheet(request):
    try:
        with open('styles.css', 'r') as f:
            css_content = f.read()
            return Response(body=css_content, 
                headers={'Content-Type': 'text/css', 'Cache-Control': 'max-age=604800'})
    except OSError:
        return Response('/* Stylesheet not found */', headers={'Content-Type': 'text/css'})


# --- Debug log viewer routes ---
@app.route('/debug')
def debug_page(request):
    # Stream HTML to minimize single large allocations
    def _stream():
        yield "<!doctype html>\n<html>\n  <head>\n    <meta charset=\"utf-8\">\n    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n    <title>CuWatch Debug Log</title>\n"
        yield "    <link rel=\"stylesheet\" href=\"https://maxcdn.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css\">\n"
        yield "    <style>body{background:#f7f9fc}.wrap{max-width:960px;margin:20px auto}pre{background:#111;color:#0f0;padding:12px;border-radius:6px;height:60vh;overflow:auto}.controls{display:flex;gap:8px;align-items:center}</style>\n  </head>\n  <body class=\"bg-light\">\n    <div class=\"wrap\">\n      <div class=\"d-flex justify-content-between align-items-center mb-2\">\n        <h3 class=\"mb-0\">Debug Log</h3>\n        <div class=\"controls\">\n          <button class=\"btn btn-sm btn-secondary\" id=\"clearBtn\">Clear</button>\n          <label class=\"mb-0\"><input type=\"checkbox\" id=\"follow\" checked> Follow</label>\n        </div>\n      </div>\n      <pre id=\"log\">Loading…</pre>\n      <p class=\"text-muted small\">Updates every 10 seconds. Shows last 200 lines.</p>\n      <a href=\"/\" class=\"btn btn-link p-0\">Back to Home</a>\n    </div>\n    <script>\n"
        yield "(function(){var pre=document.getElementById('log');var follow=document.getElementById('follow');function fetchLog(){fetch('/debug/log').then(function(r){return r.text();}).then(function(t){var atBottom=(pre.scrollTop+pre.clientHeight)>=(pre.scrollHeight-8);pre.textContent=t||'';if(follow&&follow.checked&&atBottom){pre.scrollTop=pre.scrollHeight;}}).catch(function(e){});}setInterval(fetchLog,10000);fetchLog();var c=document.getElementById('clearBtn');if(c){c.onclick=function(){fetch('/debug/clear',{method:'POST'}).then(fetchLog);};}})();\n"
        yield "    </script>\n  </body>\n</html>\n"
    return Response(body=_stream(), headers={'Content-Type': 'text/html', 'Cache-Control': 'no-cache'})


@app.route('/debug/log')
def debug_log(request):
    def _stream():
        try:
            n = len(DEBUG_LOG)
            start = 0 if n <= 200 else n - 200
            i = start
            while i < n:
                s = DEBUG_LOG[i]
                # Yield the stored string, add a newline if missing
                yield s
                if not s.endswith('\n'):
                    yield '\n'
                i += 1
        except Exception:
            # In case of any issue, yield nothing further
            if False:
                yield ''
    return Response(body=_stream(), headers={'Content-Type': 'text/plain', 'Cache-Control': 'no-cache'})


@app.route('/debug/clear', methods=['POST'])
def debug_clear(request):
    try:
        DEBUG_LOG.clear()
    except Exception:
        pass
    return Response(body='ok', headers={'Content-Type': 'text/plain', 'Cache-Control': 'no-cache'})


# Serve a lightweight bootstrap JS that defers loading of app.js
@app.route('/boot.js')
def boot_js(request):
    js = """
    (function(){
      function displayTime(){
        var now=new Date();
        var el=document.getElementById('time');
        if(el){ el.textContent=now.toLocaleTimeString(); }
      }
      setInterval(displayTime,1000);

      // Lightweight initial populate so the page shows data fast
      function populateOnce(){
        fetch('/data').then(r=>r.json()).then(function(d){
          var set=function(id,v){var e=document.getElementById(id); if(e){ e.textContent=v; }};
          set('rate', d.rate); set('muon_count', d.muon_count); set('baseline', d.baseline);
          set('threshold', d.threshold);
          set('reset_threshold', d.reset_threshold); set('runtime', d.runtime);
          var lu=document.getElementById('last_updated');
          if(lu){ lu.textContent='Last updated: '+(new Date()).toLocaleTimeString(); }
        }).catch(function(e){console.log('boot populate err', e);});
      }

      // Basic button handlers available immediately
      window.invokeMicrocontrollerMethod=function(){
        fetch('/request-shutdown',{method:'POST'}).then(r=>r.json()).catch(function(e){console.log(e);});
      };
      window.restartRequest=function(){
        fetch('/request-restart',{method:'POST'}).then(r=>r.json()).catch(function(e){console.log(e);});
      };
      window.updateThreshold=function(){
        var v=document.getElementById('thresholdInput'); if(!v||!v.value){alert('Enter threshold'); return;}
        var xhr=new XMLHttpRequest(); xhr.open('POST','/submit',true);
        xhr.setRequestHeader('Content-Type','application/x-www-form-urlencoded');
        xhr.onreadystatechange=function(){
          if(xhr.readyState===4){
            if(xhr.status===200){
              // Success, reload page
              window.location.reload();
            }else{
              // Show actual error message from server
              var msg = xhr.responseText || 'Failed to update threshold';
              alert(msg);
            }
          }
        };
        xhr.send('threshold='+encodeURIComponent(v.value));
      };

      // Defer loading of heavier logic
      function loadAppJs(){
        var s=document.createElement('script'); s.src='/app.js?v=1'; s.defer=true; document.head.appendChild(s);
      }

      window.addEventListener('load', function(){ populateOnce(); loadAppJs(); });
    })();
    """
    return Response(body=js, headers={'Content-Type':'application/javascript','Cache-Control':'max-age=604800'})


# Serve the main JS as a static resource (charts, periodic updates, lazy loads Chart.js)
@app.route('/app.js')
def app_js(request):
    js = """
    (function(){
      function loadScript(src){
        return new Promise(function(resolve, reject){
          var s=document.createElement('script'); s.src=src; s.onload=resolve; s.onerror=reject; document.head.appendChild(s);
        });
      }

      var rateChart;
      function initChart(){
        var canvas=document.getElementById('rateChart');
        if(!canvas){ return; }
        var ctx=canvas.getContext('2d');
        rateChart=new Chart(ctx,{
          type:'line',
          data:{labels:[],datasets:[{label:'Rate vs Time',data:[],borderWidth:2,fill:false}]},
          options:{responsive:true,maintainAspectRatio:true,scales:{x:{type:'time',time:{unit:'second'}},y:{beginAtZero:true}}}
        });
      }

      function saveGraphData(){
        try{
          localStorage.setItem('rateLabels',JSON.stringify(rateChart.data.labels));
          localStorage.setItem('rateData',JSON.stringify(rateChart.data.datasets[0].data));
        }catch(e){}
      }
      function loadGraphData(){
        try{
          var a=JSON.parse(localStorage.getItem('rateLabels')||'null');
          var b=JSON.parse(localStorage.getItem('rateData')||'null');
          if(a&&b&&rateChart){ rateChart.data.labels=a; rateChart.data.datasets[0].data=b; rateChart.update(); }
        }catch(e){}
      }

      function fetchHistoricalData(){
        fetch('/refresh_data').then(r=>r.json()).then(function(data){
          var now=new Date();
          rateChart.data.labels=[]; rateChart.data.datasets[0].data=[];
          for(var i=0;i<data.length;i++){
            var ts=new Date(now.getTime()-i*30000);
            rateChart.data.labels.unshift(ts);
            rateChart.data.datasets[0].data.unshift(data[i]);
          }
          rateChart.update(); saveGraphData();
        }).catch(function(e){console.log('hist err',e);});
      }

      function fetchData(){
        fetch('/data').then(r=>r.json()).then(function(d){
          var now=new Date();
          var set=function(id,v){var e=document.getElementById(id); if(e){ e.textContent=v; }};
          set('rate', d.rate); set('muon_count', d.muon_count); set('threshold', d.threshold);
          set('reset_threshold', d.reset_threshold); set('runtime', d.runtime);
          var lu=document.getElementById('last_updated');
          if(lu){ lu.textContent='Last updated: '+now.toLocaleTimeString(); }
          if(rateChart){
            rateChart.data.labels.push(now);
            rateChart.data.datasets[0].data.push(d.rate);
            var limit=new Date(now.getTime()-3600*1000);
            while(rateChart.data.labels.length>0 && rateChart.data.labels[0]<limit){
              rateChart.data.labels.shift(); rateChart.data.datasets[0].data.shift();
            }
            rateChart.update(); saveGraphData();
          }
        }).catch(function(e){console.log('data err',e);});
      }

      // Initialize after loading Chart.js and the date adapter
      function start(){
        initChart();
        loadGraphData();
        fetchHistoricalData();
        fetchData();
        setInterval(fetchData,30000);
      }

      // Lazy-load heavy libs, then start
      Promise.resolve()
        .then(function(){ return loadScript('https://cdn.jsdelivr.net/npm/chart.js'); })
        .then(function(){ return loadScript('https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns'); })
        .then(start)
        .catch(function(e){ console.log('chart libs failed', e); });
    })();
    """
    return Response(body=js, headers={'Content-Type':'application/javascript','Cache-Control':'max-age=604800'})

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
        #print(data)
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
# and readout thread. GLOBALS
shutdown_request = False
restart_request = False
muon_count = 0
iteration_count = 0
rate = 0.
waited = 0
threshold = 0
reset_threshold = 0
is_leader = True
avg_time = 0.
rates = RingBuffer.RingBuffer(120,'f')
start_time_sec = 0
last_req_ms = 0
baseline = 0
##################################################################

##################################################################

### SET UP GPIO PINS
# set up switch on pin 16
usr_switch = Pin(16, Pin.IN, Pin.PULL_DOWN)
switch_pressed = False
usr_switch.irq(trigger=Pin.IRQ_RISING, handler=usr_switch_pressed)

# # HV supply -- active low pin to turn off
# # the high voltage power supply
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
init_sdcard()
gc.collect() # early heap consolidation

server_task = None  # global handle to the running server task

async def server_monitor():
    global server_task
    while True:
        try:
            if server_task is not None and server_task.done():
                exc = server_task.exception()
                print("[monitor] server task ended", ("with exception:" if exc else "cleanly"), exc)
                if exc:
                    sys.print_exception(exc)   # <-- keep the traceback

                # attempt a restart
                server_task = asyncio.create_task(app.start_server(host='0.0.0.0', port=80, debug=False))
                print("[monitor] server restarted")
        except Exception as e:
            print("[monitor] error:", e)
        await asyncio.sleep(15) # check every 15 seconds


async def main():
    global muon_count, iteration_count, rate, waited, switch_pressed, avg_time
    global rates, threshold, reset_threshold, is_leader, start_time_sec, baseline
    global server_task
    server_task = asyncio.create_task(app.start_server(host='0.0.0.0', port=80, debug=False))
    mon_task = asyncio.create_task(server_monitor())
    try:
        ip = wlan.ifconfig()[0]
        print("[server] listening on http://%s:80" % ip)
    except Exception as e:
        print("[server] unable to get IP:", e)
    print("main() started")
    l1t = led1.toggle
    l2on = led2.on
    l2off = led2.off
    adc = ADC(Pin(26))       # create ADC object on ADC pin, Pin 26
    temperature_adc = ADC(Pin(27))  # create ADC object on ADC pin Pin 27

    readout = adc.read_u16
    # # calibrate the threshold with HV off
    # hv_power_enable.off()
    # baseline, rms = calibrate_average_rms(500)

    # # 100 counts correspond to roughly (100/(2^16))*3.3V = 0.005V. So 1000 counts
    # # is 50 mV above threshold. the signal in Sally is about 0.5V.
    # threshold = int(round(baseline + 1000.))
    # reset_threshold = round(baseline + 50.)
    # print(f"baseline: {baseline}, threshold: {threshold}, reset_threshold: {reset_threshold}")

    # calibrate the threshold with HV on
    hv_power_enable = Pin(19, Pin.OUT)
    hv_power_enable.on()

    await asyncio.sleep_ms(0)
    baseline, rms = calibrate_average_rms(500)
    await asyncio.sleep_ms(0)
    # 100 counts correspond to roughly (100/(2^16))*3.3V = 0.005V. So 1000 counts
    # is 50 mV above threshold. the signal in Sally is about 0.5V.
    threshold = int(round(baseline + 1000.))
    reset_threshold = round(baseline + 50.)
    print(f"baseline: {baseline}, threshold: {threshold}, reset_threshold: {reset_threshold}")

    coincidence_pin = None
    is_leader = check_leader_status()
    if is_leader:
        coincidence_pin = Pin(14, Pin.IN)
    else:
        coincidence_pin = Pin(14, Pin.OUT)
    print("is_leader is ", is_leader)

    f = init_file(baseline, rms, threshold, reset_threshold, now, is_leader)

    start_time_sec = time.time() # used for calculating runtime
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
    YIELD_PERIOD_MS = const(50)  # tune: 20–50 ms to taste

    dts = RingBuffer.RingBuffer(50)
    coincidence = 0
    print("[main]: start of data taking loop")
    loop_timer_time = tmeas()
    last_yield = loop_timer_time
    while True:
        iteration_count += 1
        if iteration_count % INNER_ITER_LIMIT == 0:
            avg_dt = dts.calculate_average()
            if avg_dt == 0.:
                rate = 0.
            else:
                rate = 1000./avg_dt
            tdiff = time.ticks_diff(tmeas(), loop_timer_time)
            avg_time = tdiff/INNER_ITER_LIMIT
            loop_timer_time = tmeas()
            try:
                delta_req = time.ticks_diff(loop_timer_time, last_req_ms)
            except Exception:
                delta_req = -1
            print(f"iter {iteration_count}, # {muon_count}, {rate:.1f} Hz, {gc.mem_free()} free, "
                f"avg time {avg_time:.3f} ms, last_req_delta={delta_req} ms, "
                f"last_yield_delta={time.ticks_diff(loop_timer_time, last_yield)} ms")
            l1t()
            # update rates ring buffer every half minute. this time needs to be synched with the web server
            if time.ticks_diff(loop_timer_time, tlast) >= 30000:  # 30,000 ms = 30 seconds
                rates.append(round(rate, 2))
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
                    # we yield here to let the web server run. Most of the time if we get here something
                    # has gone wrong.
                    await asyncio.sleep_ms(5) # yield to the web server running in the other thread
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
        if iteration_count % 3_000 == 0:
            last_yield = tmeas()
            await asyncio.sleep_ms(0) # yield to the web server running in the other thread
            # now_ticks = tmeas()
            # if time.ticks_diff(now_ticks, last_yield) >= YIELD_PERIOD_MS:
            #     await asyncio.sleep_ms(0) # this yields to the web server running in the other thread
            #     last_yield = now_ticks
        # # Cooperative yield with a budget: only when idle and at most every YIELD_PERIOD_MS
        # if adc_value <= threshold:
        #     now_ticks = tmeas()
        #     if time.ticks_diff(now_ticks, last_yield) >= YIELD_PERIOD_MS:
        #         await asyncio.sleep_ms(0)
        #         last_yield = now_ticks
        if shutdown_request or switch_pressed or restart_request:
            print("tight loop shutdown, waited is ", waited)
            break
    try:
        mon_task.cancel()
    except Exception:
        pass
    # Microdot's shutdown() is synchronous; do not await it on MicroPython
    app.shutdown()
    f.close()
    await server_task
    # f.close()
    # await server

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
    sys.print_exception(e)
    try:
        f.close()
    except:
        pass
    unmount_sdcard()
    print("done")

if restart_request:
    machine.reset()
