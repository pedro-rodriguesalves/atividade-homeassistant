"""Gateway DIDATICO MQTT-SN (UDP) -> MQTT (TCP).

Subconjunto MQTT-SN 1.2: SEARCHGW, CONNECT, REGISTER, PUBLISH QoS0,
PINGREQ e DISCONNECT. Nao e um gateway MQTT-SN completo.
"""

import configparser
import json
import logging
import signal
import socket
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from mqttsn import (
    ACCEPTED,
    REJECTED_INVALID_TOPIC_ID,
    REJECTED_NOT_SUPPORTED,
    Type,
    pack,
    unpack,
)

LOG = logging.getLogger("mqttsn-gateway")


@dataclass
class Session:
    client_id: str
    by_name: dict[str, int] = field(default_factory=dict)
    by_id: dict[int, str] = field(default_factory=dict)
    next_topic_id: int = 1

    def register(self, name: str) -> int:
        if name not in self.by_name:
            if self.next_topic_id > 65535:
                raise ValueError("Limite de topic IDs da sessao")
            topic_id = self.next_topic_id
            self.next_topic_id += 1
            self.by_name[name] = topic_id
            self.by_id[topic_id] = name
        return self.by_name[name]


class MQTT_SN_Handler:
    def __init__(
        self,
        send: Callable[[bytes, tuple[str, int]], None],
        publish: Callable[[str, bytes], bool],
        allowed_prefix: str = "iot/",
    ) -> None:
        self.send = send
        self.publish = publish
        self.allowed_prefix = allowed_prefix
        self.sessions: dict[tuple[str, int], Session] = {}

    def reply(self, address: tuple[str, int], kind: Type, body: bytes = b"") -> None:
        self.send(pack(kind, body), address)

    def handle(self, datagram: bytes, address: tuple[str, int]) -> None:
        try:
            kind, data = unpack(datagram)
            if kind == Type.SEARCHGW:
                # ID do gateway = 1, sem endereco (remetente do UDP e suficiente).
                self.reply(address, Type.GWINFO, b"\x01")
            elif kind == Type.CONNECT:
                self.on_connect(data, address)
            elif kind == Type.REGISTER:
                self.on_register(data, address)
            elif kind == Type.PUBLISH:
                self.on_publish(data, address)
            elif kind == Type.PINGREQ:
                self.reply(address, Type.PINGRESP)
            elif kind == Type.DISCONNECT:
                session = self.sessions.pop(address, None)
                LOG.info("DISCONNECT MQTT-SN %s (%s)", address, session.client_id if session else "?")
                self.reply(address, Type.DISCONNECT)
            else:
                LOG.warning("Tipo MQTT-SN 0x%02x nao implementado: %s", kind, address)
        except (ValueError, UnicodeDecodeError) as exc:
            LOG.warning("Datagrama invalido de %s: %s", address, exc)

    def on_connect(self, data: bytes, address: tuple[str, int]) -> None:
        if len(data) < 5:
            raise ValueError("CONNECT deve conter flags, protocolo, duration e clientId")
        flags, proto = data[0], data[1]
        client_id = data[4:].decode("utf-8")
        if proto != 1 or (flags & 0x08) or not client_id:
            # Sem suporte a mensagens WILL MQTT-SN.
            self.reply(address, Type.CONNACK, bytes([REJECTED_NOT_SUPPORTED]))
            return
        self.sessions[address] = Session(client_id=client_id)
        LOG.info("CONNECT MQTT-SN cliente=%s de=%s", client_id, address)
        self.reply(address, Type.CONNACK, bytes([ACCEPTED]))

    def on_register(self, data: bytes, address: tuple[str, int]) -> None:
        if len(data) < 5:
            raise ValueError("REGISTER incompleto")
        session = self.sessions.get(address)
        msg_id = data[2:4]
        topic = data[4:].decode("utf-8")
        if session is None or not topic.startswith(self.allowed_prefix) or any(x in topic for x in ("+", "#", "\x00")):
            self.reply(address, Type.REGACK, b"\x00\x00" + msg_id + bytes([REJECTED_NOT_SUPPORTED]))
            LOG.warning("REGISTER rejeitado de=%s topico=%r", address, topic)
            return
        topic_id = session.register(topic)
        self.reply(address, Type.REGACK, topic_id.to_bytes(2, "big") + msg_id + bytes([ACCEPTED]))
        LOG.info("REGISTER MQTT-SN cliente=%s topicId=%s topico=%s", session.client_id, topic_id, topic)

    def on_publish(self, data: bytes, address: tuple[str, int]) -> None:
        if len(data) < 5:
            raise ValueError("PUBLISH incompleto")
        flags = data[0]
        topic_id = int.from_bytes(data[1:3], "big")
        msg_id = data[3:5]
        value = data[5:]
        session = self.sessions.get(address)
        topic = session.by_id.get(topic_id) if session else None
        # QoS 0 + topic normal registrado, apenas.
        if flags & 0x63 or topic is None:
            if (flags & 0x60) == 0x20:  # QoS 1: retornar erro explicito.
                code = REJECTED_NOT_SUPPORTED if flags & 0x63 else REJECTED_INVALID_TOPIC_ID
                self.reply(address, Type.PUBACK, data[1:3] + msg_id + bytes([code]))
            LOG.warning("PUBLISH rejeitado cliente=%s topicId=%s flags=0x%02x", address, topic_id, flags)
            return
        if self.publish(topic, value):
            LOG.info("PUBLISH MQTT-SN -> MQTT topico=%s mensagem=%s", topic, value.decode("utf-8", errors="replace"))
        else:
            LOG.warning("Broker MQTT indisponivel: mensagem descartada (MQTT-SN QoS0)")


class GatewayApp:
    def __init__(self, config_file: str):
        config = configparser.ConfigParser()
        if not config.read(config_file):
            raise FileNotFoundError(config_file)
        self.cfg = config
        self.client = None
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(1.0)
        self.stopping = threading.Event()
        self.mqtt_connected = threading.Event()
        self.handler = MQTT_SN_Handler(
            send=self.socket.sendto,
            publish=self.publish,
            allowed_prefix=config.get("mqttsn", "allowed_topic_prefix", fallback="iot/"),
        )

    def mqtt_on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code != 0:
            LOG.error("Falha ao conectar broker: %s", reason_code)
            return
        self.mqtt_connected.set()
        mqtt_cfg = self.cfg["mqtt"]
        # Publica 3 entidades de Home Assistant por MQTT Discovery.
        device = {
            "identifiers": ["laboratorio_sensor_mqttsn_01"],
            "name": "Sensores MQTT-SN (laboratorio)",
            "manufacturer": "Laboratorio IoT",
            "model": "Publisher UDP simulado",
        }
        entities = [
            (
                mqtt_cfg["discovery_topic"],
                {
                    "name": "Temperatura MQTT-SN",
                    "unique_id": "laboratorio_temperatura_mqttsn_01",
                    "state_topic": mqtt_cfg["state_topic"],
                    "device_class": "temperature",
                    "state_class": "measurement",
                    "unit_of_measurement": "°C",
                },
            ),
            (
                mqtt_cfg["humidity_discovery_topic"],
                {
                    "name": "Umidade MQTT-SN",
                    "unique_id": "laboratorio_umidade_mqttsn_01",
                    "state_topic": mqtt_cfg["humidity_state_topic"],
                    "device_class": "humidity",
                    "state_class": "measurement",
                    "unit_of_measurement": "%",
                },
            ),
            (
                mqtt_cfg["presence_discovery_topic"],
                {
                    "name": "Presença MQTT-SN",
                    "unique_id": "laboratorio_presenca_mqttsn_01",
                    "state_topic": mqtt_cfg["presence_state_topic"],
                    "device_class": "occupancy",
                    "payload_on": "ON",
                    "payload_off": "OFF",
                },
            ),
        ]
        for discovery_topic, entity in entities:
            entity.update({
                "availability_topic": mqtt_cfg["availability_topic"],
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": device,
            })
            client.publish(discovery_topic, json.dumps(entity), qos=1, retain=True)
        client.publish(mqtt_cfg["availability_topic"], "online", qos=1, retain=True)
        LOG.info("MQTT conectado. Discovery de temperatura, umidade e presenca publicado")

    def mqtt_on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        self.mqtt_connected.clear()
        LOG.warning("MQTT desconectado: %s", reason_code)

    def publish(self, topic: str, payload: bytes) -> bool:
        if self.client is None or not self.mqtt_connected.is_set():
            return False
        try:
            info = self.client.publish(topic, payload, qos=1, retain=True)
            return info.rc == 0
        except Exception as exc:
            LOG.warning("Falha de publicacao MQTT: %s", exc)
            return False

    def stop(self, *_args) -> None:
        self.stopping.set()

    def run(self) -> None:
        # Import aqui permite testar o protocolo UDP sem a dependencia externa.
        import paho.mqtt.client as mqtt

        mq = self.cfg["mqtt"]
        sn = self.cfg["mqttsn"]
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=mq["client_id"],
            protocol=mqtt.MQTTv311,
        )
        self.client.on_connect = self.mqtt_on_connect
        self.client.on_disconnect = self.mqtt_on_disconnect
        self.client.will_set(mq["availability_topic"], "offline", qos=1, retain=True)
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)
        self.client.connect_async(mq["host"], mq.getint("port"), keepalive=60)
        self.client.loop_start()
        self.socket.bind((sn["bind"], sn.getint("port")))
        LOG.info("MQTT-SN escutando UDP %s:%s", sn["bind"], sn["port"])

        try:
            while not self.stopping.is_set():
                try:
                    packet, addr = self.socket.recvfrom(65535)
                    self.handler.handle(packet, addr)
                except socket.timeout:
                    continue
                except OSError:
                    if not self.stopping.is_set():
                        LOG.exception("Erro no socket UDP")
        finally:
            self.socket.close()
            if self.mqtt_connected.is_set():
                result = self.client.publish(mq["availability_topic"], "offline", qos=1, retain=True)
                result.wait_for_publish(timeout=2)
            self.client.disconnect()
            self.client.loop_stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = GatewayApp(str(Path(__file__).with_name("gateway.ini")))
    signal.signal(signal.SIGINT, app.stop)
    signal.signal(signal.SIGTERM, app.stop)
    app.run()


if __name__ == "__main__":
    main()
