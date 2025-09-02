#! /usr/bin/env python

import asyncio
from amqtt.client import MQTTClient
from amqtt.broker import Broker
import sqlite3
import json

# Use plugin-based configuration for amqtt broker (as per latest recommendations)
broker_config = {
'listeners': {
'default': {
    'type': 'tcp',
    'bind': '0.0.0.0:1883'
},
'ws': {
    'type': 'ws',
    'bind': '0.0.0.0:9001'
},
'secure': {
    'type': 'tcp',
    'bind': '0.0.0.0:8883',
}
},
'plugins': {
# Authentication plugins
'amqtt.plugins.authentication.AnonymousAuthPlugin': {
    'allow_anonymous': True
},

# Topic access control
'amqtt.plugins.topic_checking.TopicTabooPlugin': {
},
'amqtt.plugins.topic_checking.TopicAccessControlListPlugin': {
    'acl': {
        'anonymous': ['test/+', 'public/+'],
        'user1': ['user1/+', 'shared/+'],
        'admin': ['#']  # Admin can access all topics
    }
},

# System monitoring
'amqtt.plugins.sys.broker.BrokerSysPlugin': {
    'sys_interval': 20
},

# Logging plugins
'amqtt.plugins.logging_amqtt.EventLoggerPlugin': {
},
'amqtt.plugins.logging_amqtt.PacketLoggerPlugin': {
},
},

# # # Additional broker settings
# # 'timeout-disconnect-delay': 2,
    # # 'timeout-keep-alive': 60,
    # # 'max-connections': 50000,
    # # 'max-inflight-messages': 20,
    
    # # Logging configuration
    # 'logging': {
    #     'version': 1,
    #     'formatters': {
    #         'default': {
    #             'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    #         }
    #     },
    #     'handlers': {
    #         'console': {
    #             'class': 'logging.StreamHandler',
    #             'formatter': 'default',
    #             'level': 'INFO'
    #         },
    #         'file': {
    #             'class': 'logging.FileHandler',
    #             'filename': '/app/broker.log',
    #             'formatter': 'default',
    #             'level': 'DEBUG'
    #         }
    #     },
    #     'loggers': {
    #         'amqtt': {
    #             'level': 'INFO',
    #             'handlers': ['console', 'file']
    #         }
    #     }
    # }
}

# Alternative simplified configuration for development
dev_broker_config = {
    'listeners': {
        'default': {
            'type': 'tcp',
            'bind': '0.0.0.0:1883'
        }
    },
    'sys_interval': 10,
    'plugins': {
        'amqtt.plugins.authentication.AnonymousAuthPlugin': {
            'allow_anonymous': True
        },
        'amqtt.plugins.sys.broker.BrokerSysPlugin': {
            'sys_interval': 30
        },
        'amqtt.plugins.logging_amqtt.EventLoggerPlugin': {}
    }
}

def init_db(json_keys):
    conn = sqlite3.connect('mqtt_test_data.db')
    c = conn.cursor()
    # Create table with columns for each JSON key
    columns = ', '.join([f'"{key}" TEXT' for key in json_keys])
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS mqtt_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {columns}
        )
    ''')
    conn.commit()
    conn.close()

async def handle_mqtt_messages():
    client = MQTTClient()
    await client.connect('mqtt://localhost:1883/')
    await client.subscribe([
        ('test/topic', 0),  # Subscribe to specific topic
        ('+/+', 0),         # Subscribe to all topics (wildcard)
    ])
    
    conn = sqlite3.connect('mqtt_data.db')
    c = conn.cursor()
    table_initialized = False
    
    try:
        while True:
            message = await client.deliver_message()
            packet = message.publish_packet
            topic = packet.variable_header.topic_name
            payload = packet.payload.data.decode('utf-8')
            
            print(f"Received message on topic '{topic}': {payload}")
            
            try:
                msg = json.loads(payload)
                print(f"Received JSON: {msg}")
                if not table_initialized:
                    init_db(msg.keys())
                    table_initialized = True
                # Insert the JSON data into the table
                keys = ', '.join([f'"{k}"' for k in msg.keys()])
                placeholders = ', '.join(['?'] * len(msg))
                values = list(msg.values())
                c.execute(f'INSERT INTO mqtt_messages ({keys}) VALUES ({placeholders})', values)
                conn.commit()
            except json.JSONDecodeError:
                print(f"Message is not JSON: {payload}")
            except Exception as e:
                print(f"Error processing message: {e}")
    finally:
        conn.close()
        await client.disconnect()

async def start_broker():
    broker = Broker(broker_config)
    try:
        await broker.start()
        print("MQTT Broker started on port 1883")
        
        # Start the message handler
        asyncio.create_task(handle_mqtt_messages())
        
        print("Press Ctrl+C to stop the broker")
        # Keep the broker running indefinitely
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down broker...")
    finally:
        await broker.shutdown()

if __name__ == '__main__':
    try:
        asyncio.run(start_broker())
    except KeyboardInterrupt:
        print("Broker stopped.")


