"""Some code to test the CSV downloading functionality of the Microdot web server."""
import uos as os
from microdot import Microdot, Response
import machine
import sdcard
import uos as os
import ujson as json

# conclusions:
# sorting the file list can be problematic if the list is too long
# using stat or the name of the file names doesn't help; it is the sort itself
# that requires too much memory

# Initialize the Microdot app
app = Microdot()

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


# Set default content type
Response.default_content_type = 'text/html'

# Path to the SD card directory where CSV files are located
SD_DIRECTORY = '/sd'

# Helper function to concatenate paths (since os.path.join is not available)
def join_path(directory, filename):
    if directory.endswith('/'):
        return directory + filename
    else:
        return directory + '/' + filename
# Helper function to extract time from filename (expected format: muon_data_YYYYMMDD_HHMM.csv)
def extract_timestamp_from_filename(filename):
    try:
        # Example: muon_data_20231018_0930.csv -> extract "20231018_0930"
        timestamp_str = filename.split('_')[2] + filename.split('_')[3].split('.')[0]
        # Convert "YYYYMMDDHHMM" to tuple (YYYY, MM, DD, HH, MM) for sorting
        return (int(timestamp_str[:4]), int(timestamp_str[4:6]), int(timestamp_str[6:8]), int(timestamp_str[8:10]), int(timestamp_str[10:12]))
    except (IndexError, ValueError):
        return (0,)  # Return a default value for files that don't match the expected format

# Main route that serves the form, graph, and global variables
@app.route('/', methods=['GET'])
def index(request):
    html = """
    <html>
        <head>
            <title>CuWatch</title>
            <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css">
        </head>
        <body class="bg-light">
            <div class="container">
                <h1 class="my-4 text-center">CuWatch Status and Configuration</h1>
                
                <a href="/download">Download CSV Files</a>  <!-- Link to the CSV download page -->
                
                <h3 class="my-4">Current Time (JavaScript):</h3>
                <p>Time: <span id="time" class="font-weight-bold"></span></p>
            </div>
        </body>
    </html>
    """
    return Response(body=html, headers={'Content-Type': 'text/html'})

# Route to list and allow downloads of CSV files from the /sd directory
@app.route('/download', methods=['GET'])
def download_page(request):
    files = []

    # Get list of .csv files in the /sd directory
    try:
        if os.stat(SD_DIRECTORY):  # Check if directory exists
            files = [f for f in os.listdir(SD_DIRECTORY) if f.endswith('.csv')]

        # Sort files based on the extracted timestamp from the filename (most recent first)
        files = sorted(files, key=lambda x: extract_timestamp_from_filename(x), reverse=True)
    except OSError:
        files = []  # Handle case where SD card is not mounted or directory doesn't exist

    # Generate HTML for displaying the list of files with download links
    file_list_html = "<ul>"
    for file in files:
        file_list_html += f'<li><a href="/download_file?file={file}">{file}</a></li>'
    file_list_html += "</ul>"

    html = f"""
    <html>
        <head>
            <title>Download CSV Files</title>
            <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css">
        </head>
        <body class="bg-light">
            <div class="container">
                <h1 class="my-4 text-center">Download CSV Files</h1>
                {file_list_html}
                <a href="/">Back to Home</a>
            </div>
        </body>
    </html>
    """
    return Response(body=html, headers={'Content-Type': 'text/html'})

# Route to serve a specific CSV file for download
@app.route('/download_file', methods=['GET'])
def download_file(request):
    file_name = request.args.get('file')
    file_path = join_path(SD_DIRECTORY, file_name)

    try:
        if os.stat(file_path) and file_name.endswith('.csv'):
            # Read the file content and serve it
            with open(file_path, 'r') as f:
                file_content = f.read()

            # Return the file content as a CSV download
            return Response(body=file_content, headers={
                'Content-Type': 'text/csv',
                'Content-Disposition': f'attachment; filename="{file_name}"'
            })
    except OSError:
        return Response('File not found', 404)

# mount SD card
sd = init_sdcard()
# Run the server
try:
    app.run(host='0.0.0.0', port=80)
finally:
    unmount_sdcard()
    print("Server stopped and SD card unmounted.")
