# Compila no mesmo Debian usado no runtime, evitando incompatibilidade de glibc.
FROM debian:bookworm-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY publisher/client.c ./client.c
RUN gcc -std=c11 -O2 -Wall -Wextra -Wpedantic -o /src/mqttsn-client /src/client.c

FROM debian:bookworm-slim
COPY --from=builder /src/mqttsn-client /usr/local/bin/mqttsn-client
ENV GATEWAY_HOST=gateway GATEWAY_PORT=1884 CLIENT_ID=sensores-sala-01 \
    MQTT_TOPIC=iot/sala/temperatura HUMIDITY_TOPIC=iot/sala/umidade \
    PRESENCE_TOPIC=iot/sala/presenca INTERVAL=3 COUNT=0 PING_EVERY=10
STOPSIGNAL SIGTERM
CMD ["/usr/local/bin/mqttsn-client"]
