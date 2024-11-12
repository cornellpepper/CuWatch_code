#
# start the wifi connection on boot
#
from machine import Pin
import network
import time
import my_secrets

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
    led2.value(1)
    led1.value(0)
    while connection_timeout > 0:
        if wlan.status() >= network.STAT_GOT_IP:
            break
        connection_timeout -= 1
        print(f"\b\b\b{cycle[i]}", end="")
        i = (i + 1) % 4
        time.sleep(1)
        led1.toggle()
        led2.toggle()
    
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

def main():
    led1 = Pin('LED', Pin.OUT)
    led2 = Pin(15, Pin.OUT) # local LED on pepper carrier board

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

if __name__ == "__main__":
    main()

# End of boot.py