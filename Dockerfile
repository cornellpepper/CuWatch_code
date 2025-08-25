ARG BASE_IMAGE=python:3.9-slim
FROM ${BASE_IMAGE}

WORKDIR /app
COPY src/test_server.py .

RUN pip install hbmqtt

EXPOSE 1883

CMD ["python", "test_server.py"]