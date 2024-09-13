import network

# Initialize the network interface (Wi-Fi)
wlan = network.WLAN(network.STA_IF)

# Activate the network interface
wlan.active(True)

# Get the MAC address
mac = wlan.config('mac')

# Print the MAC address in a readable format
print("Wireless MAC address: ", end='')
print(':'.join('%02x' % b for b in mac))
