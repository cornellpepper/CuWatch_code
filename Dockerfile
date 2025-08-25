ARG BASE_IMAGE=amqtt/amqtt
FROM ${BASE_IMAGE}

WORKDIR /app
COPY src/test_server.py .

EXPOSE 1883
EXPOSE 9001
EXPOSE 8883


CMD ["python", "test_server.py"]
