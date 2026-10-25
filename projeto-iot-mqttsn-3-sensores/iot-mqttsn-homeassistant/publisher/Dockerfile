FROM python:3.12-slim

WORKDIR /app
COPY shared/mqttsn.py /app/mqttsn.py
COPY publisher/publisher.py /app/publisher.py

ENV PYTHONUNBUFFERED=1
CMD ["python", "-u", "/app/publisher.py"]
