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


def generate_dummy_data():
    muon_count = random.randint(0, 100)
    adc_value = random.randint(0, 4095)
    temperature_adc_value = random.randint(0, 4095)
    dt = random.randint(0, 10)
    end_time = int(time.time())
    wait_counts = random.randint(0, 1000)
    coincidence = random.choice([0, 1])
    # Create a dictionary to hold the data.
    return {
        "muon_count": muon_count,
        "adc_value": adc_value,
        "temperature_adc_value": temperature_adc_value,
        "dt": dt,
        "end_time": end_time,
        "wait_counts": wait_counts,
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

topic = "test/event"

client = mqtt.Client()
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_publish = on_publish
client.on_message = on_message

# Set keepalive to detect disconnections faster
client.connect("localhost", 1883, 10)  # 10 second keepalive
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
        time.sleep(5)
except KeyboardInterrupt:
    print("Exiting...")
    client.loop_stop()
    client.disconnect()
