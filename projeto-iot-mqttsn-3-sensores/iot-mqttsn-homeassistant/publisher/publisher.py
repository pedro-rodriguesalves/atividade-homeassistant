"""Simulador MQTT-SN/UDP: CONNECT, REGISTER e PUBLISH QoS 0."""

import logging
import os
import signal
import socket
import time
from mqttsn import ACCEPTED, Type, pack, unpack

LOG = logging.getLogger("publisher-mqttsn")
STOP = False


def on_stop(*_args) -> None:
    global STOP
    STOP = True


def request(sock, address, message, expected_type, attempts=20):
    """Tenta completar o handshake UDP sem sair se o gateway esta iniciando."""
    for attempt in range(1, attempts + 1):
        if STOP:
            raise InterruptedError("Publisher interrompido")
        sock.sendto(message, address)
        try:
            data, src = sock.recvfrom(65535)
            if src[0] != socket.gethostbyname(address[0]) or src[1] != address[1]:
                continue
            kind, payload = unpack(data)
            if kind == expected_type:
                return payload
            LOG.warning("Resposta inesperada: 0x%02x", kind)
        except socket.timeout:
            LOG.warning("Gateway sem resposta (%d/%d)", attempt, attempts)
    raise TimeoutError("Nao foi possivel estabelecer sessao MQTT-SN")


def handshake(sock, address, client_id: str, topics: list[str]) -> dict[str, int]:
    """Conecta ao gateway e registra todos os topicos desta sessao."""
    client_bytes = client_id.encode("utf-8")
    conn_body = b"\x04\x01\x00\x3c" + client_bytes
    result = request(sock, address, pack(Type.CONNECT, conn_body), Type.CONNACK)
    if result != bytes([ACCEPTED]):
        raise RuntimeError(f"CONNECT recusado: {result.hex()}")
    LOG.info("CONNACK aceito para %s", client_id)

    ids: dict[str, int] = {}
    for msg_id, topic in enumerate(topics, start=1):
        reg_body = b"\x00\x00" + msg_id.to_bytes(2, "big") + topic.encode("utf-8")
        reg = request(sock, address, pack(Type.REGISTER, reg_body), Type.REGACK)
        if (len(reg) != 5 or reg[2:4] != msg_id.to_bytes(2, "big")
                or reg[4] != ACCEPTED):
            raise RuntimeError(f"REGACK rejeitado/invalido para {topic}: {reg.hex()}")
        topic_id = int.from_bytes(reg[:2], "big")
        if topic_id == 0:
            raise RuntimeError("Gateway retornou topic ID zero")
        ids[topic] = topic_id
        LOG.info("REGACK aceito topico=%s topicId=%s", topic, topic_id)
    return ids


def send_value(sock, address, topic: str, topic_id: int, value: str, unit: str = "") -> None:
    """Publica payload UTF-8 com MQTT-SN PUBLISH QoS 0."""
    payload = value.encode("utf-8")
    body = b"\x00" + topic_id.to_bytes(2, "big") + b"\x00\x00" + payload
    sock.sendto(pack(Type.PUBLISH, body), address)
    LOG.info("PUBLISH MQTT-SN topico=%s valor=%s%s", topic, value, unit)


def run() -> None:
    host = os.getenv("GATEWAY_HOST", "gateway")
    port = int(os.getenv("GATEWAY_PORT", "1884"))
    temp_topic = os.getenv("MQTT_TOPIC", "iot/sala/temperatura")
    humidity_topic = os.getenv("HUMIDITY_TOPIC", "iot/sala/umidade")
    presence_topic = os.getenv("PRESENCE_TOPIC", "iot/sala/presenca")
    topics = [temp_topic, humidity_topic, presence_topic]
    if len(set(topics)) != len(topics):
        raise ValueError("Os tres topicos MQTT-SN devem ser diferentes")
    client_id = os.getenv("CLIENT_ID", "sensores-sala-01")
    interval = float(os.getenv("INTERVAL", "3"))
    count = int(os.getenv("COUNT", "0"))
    address = (host, port)
    if interval <= 0 or count < 0:
        raise ValueError("INTERVAL deve ser > 0; COUNT deve ser >= 0")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(2)
        topic_ids = handshake(sock, address, client_id, topics)
        seq = 0
        last_handshake = time.monotonic()
        while not STOP and (count == 0 or seq < count):
            # Periodicamente refaz registro para recuperar a sessao caso o gateway reinicie.
            if time.monotonic() - last_handshake > 30:
                topic_ids = handshake(sock, address, client_id, topics)
                last_handshake = time.monotonic()

            # Dados DIDATICOS gerados no publisher; nao ha sensores fisicos.
            temperature = 23.0 + 0.3 * (seq % 14)     # 23.0 a 26.9 graus
            humidity = 45 + (seq * 3) % 30            # 45% a 72%
            presence = "ON" if seq % 8 < 3 else "OFF"  # Movimento/presenca simulada

            send_value(sock, address, temp_topic, topic_ids[temp_topic], f"{temperature:.1f}", " °C")
            send_value(sock, address, humidity_topic, topic_ids[humidity_topic], str(humidity), " %")
            send_value(sock, address, presence_topic, topic_ids[presence_topic], presence)
            seq += 1
            until = time.monotonic() + interval
            while not STOP:
                remaining = until - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(0.2, remaining))
        try:
            sock.sendto(pack(Type.DISCONNECT), address)
        except OSError:
            pass
        LOG.info("Publisher finalizado; ciclos=%s; publicacoes=%s", seq, seq * 3)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, on_stop)
    signal.signal(signal.SIGINT, on_stop)
    run()
