FROM python:3.12-slim

WORKDIR /app
COPY gateway/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY shared/mqttsn.py /app/mqttsn.py
COPY gateway/gateway.py /app/gateway.py
COPY gateway/gateway.ini /app/gateway.ini

ENV PYTHONUNBUFFERED=1
CMD ["python", "-u", "/app/gateway.py"]
