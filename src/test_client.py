#! /usr/bin/env python
import random
import time
import json
import paho.mqtt.client as mqtt


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected successfully")
        client.subscribe("test/topic")
    else:
        print(f"Failed to connect, return code {rc}")


def on_disconnect(client, userdata, rc):
    if rc != 0:
        print("Unexpected disconnection from broker")
    else:
        print("Disconnected from broker")


def on_publish(client, userdata, mid):
    print(f"Message {mid} published successfully")


def on_message(client, userdata, msg):
    print(f"Received message on topic {msg.topic}: {msg.payload.decode()}")

muon_count = 0

def generate_dummy_data():
    global muon_count
    device_number = random.randint(10,13)
    #muon_count = random.randint(0, 100)
    muon_count = muon_count + 1
    adc_value = random.randint(0, 4095)
    temperature_adc_value = random.randint(0, 4095)
    dt = random.randint(0, 10)
    current_time = time.time()
    if not hasattr(generate_dummy_data, "last_event_time"):
        generate_dummy_data.last_event_time = current_time
    end_time = int((current_time - generate_dummy_data.last_event_time) * 1000)
    generate_dummy_data.last_event_time = current_time
    wait_counts = random.randint(0, 1000)
    coincidence = random.choice([0, 1])
    # Create a dictionary to hold the data.
    return {
        "device_number": 1,
        "muon_count": muon_count,
        "adc_v": adc_value,
        "temp_adc_v": temperature_adc_value,
        "dt": dt,
        "end_time": end_time,
        "wait_cnt": wait_counts,
        "coincidence": coincidence
    }

# publish dummy data to a topic as JSON
def publish_data(client, topic):
    if not client.is_connected():
        print("Client not connected to broker!")
        return False
    
    data = generate_dummy_data()
    data_json = json.dumps(data)
    try:
        result = client.publish(topic, data_json)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print(f"Published data: {data_json} to topic: {topic}")
            return True
        else:
            print(f"Failed to publish data, error code: {result.rc}")
            return False
    except Exception as e:
        print(f"Error publishing data: {e}")
        return False

topic = "telemetry/dev-001"

client = mqtt.Client()
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_publish = on_publish
client.on_message = on_message

# Set keepalive to detect disconnections faster
#client.connect("localhost", 1883, 10)  # 10 second keepalive
#client.connect("10.49.72.125", 1883, 10)  # 10 second keepalive
client.connect("192.168.4.62", 1883, 10)  # 10 second keepalive
client.loop_start()

try:
    while True:
        success = publish_data(client, topic)
        if not success:
            print("Attempting to reconnect...")
            try:
                client.reconnect()
            except Exception as e:
                print(f"Reconnection failed: {e}")
        sleeptime = random.randint(1,6)
        time.sleep(sleeptime)
except KeyboardInterrupt:
    print("Exiting...")
    client.loop_stop()
    client.disconnect()
