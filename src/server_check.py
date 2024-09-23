#! /usr/bin/env python
import requests
import time
import os
from datetime import datetime

# The URL of the server to check
url = "http://example.com"  # Replace with your server's URL

# Interval between checks in seconds (60 seconds = 1 minute)
check_interval = 60

# Log file settings
log_dir = "./logs"
max_log_size = 1024 * 1024  # 1MB max log file size

# Track total checks and failures
total_checks = 0
failed_checks = 0

# Ensure the log directory exists
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

def get_log_file_name():
    # Generate a log file name with the current date
    timestamp = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(log_dir, f"server_check_{timestamp}.log")

def rotate_log_file(log_file):
    # Rotate log file if it exceeds the max size
    if os.path.exists(log_file) and os.path.getsize(log_file) > max_log_size:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        rotated_log_file = log_file.replace(".log", f"_{timestamp}_old.log")
        os.rename(log_file, rotated_log_file)

def log_result(status, message):
    # Log the result to the current log file
    log_file = get_log_file_name()
    
    # Rotate the log file if it's too large
    rotate_log_file(log_file)
    
    # Write log entry
    with open(log_file, 'a') as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{timestamp}] {status}: {message}\n")

def check_server():
    global total_checks, failed_checks
    try:
        # Send a GET request to the server
        response = requests.get(url, timeout=10)
        total_checks += 1
        
        # Check if the status code is 200 (OK)
        if response.status_code == 200:
            log_result("SUCCESS", f"Server is UP. Status Code: {response.status_code}")
        else:
            failed_checks += 1
            log_result("FAILURE", f"Server is DOWN. Status Code: {response.status_code}")

    except requests.ConnectionError:
        total_checks += 1
        failed_checks += 1
        log_result("FAILURE", "Server is DOWN. Failed to connect.")
    except requests.Timeout:
        total_checks += 1
        failed_checks += 1
        log_result("FAILURE", "Server is DOWN. Request timed out.")
    except Exception as e:
        total_checks += 1
        failed_checks += 1
        log_result("FAILURE", f"An error occurred: {e}")

if __name__ == "__main__":
    # Loop to continuously check the server every minute
    while True:
        print(f"Checking server status at {time.strftime('%Y-%m-%d %H:%M:%S')}...")
        check_server()
        
        # Calculate and print the fraction of failed checks
        if total_checks > 0:
            failure_fraction = failed_checks / total_checks
            print(f"Total checks: {total_checks}, Failed checks: {failed_checks}, Failure fraction: {failure_fraction:.2%}")

        # Wait for the specified interval before checking again
        time.sleep(check_interval)

