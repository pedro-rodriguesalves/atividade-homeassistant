"""Testes locais sem Docker nem broker para a codificacao e o gateway."""

import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "shared"))
sys.path.insert(0, str(BASE / "gateway"))

from mqttsn import ACCEPTED, REJECTED_NOT_SUPPORTED, Type, pack, unpack
from gateway import MQTT_SN_Handler


class ProtocolTest(unittest.TestCase):
    def test_short_frame(self):
        original = pack(Type.PUBLISH, b"abc")
        self.assertEqual(original, b"\x05\x0cabc")
        self.assertEqual(unpack(original), (Type.PUBLISH, b"abc"))

    def test_extended_frame(self):
        packet = pack(Type.PUBLISH, b"A" * 300)
        self.assertEqual(packet[0], 1)
        self.assertEqual(int.from_bytes(packet[1:3], "big"), len(packet))
        self.assertEqual(unpack(packet), (Type.PUBLISH, b"A" * 300))

    def test_malformed_length(self):
        with self.assertRaises(ValueError):
            unpack(b"\x04\x04")


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.published = []
        self.addr = ("127.0.0.1", 40000)

        def fake_send(data, addr):
            self.sent.append((unpack(data), addr))

        def fake_publish(topic, payload):
            self.published.append((topic, payload))
            return True

        self.handler = MQTT_SN_Handler(fake_send, fake_publish)

    def connect(self):
        self.handler.handle(pack(Type.CONNECT, b"\x04\x01\x00\x3ccliente-test"), self.addr)
        self.assertEqual(self.sent[-1][0], (Type.CONNACK, b"\x00"))

    def register(self):
        reg_body = b"\x00\x00\x00\x01iot/sala/temperatura"
        self.handler.handle(pack(Type.REGISTER, reg_body), self.addr)
        kind, body = self.sent[-1][0]
        self.assertEqual(kind, Type.REGACK)
        self.assertEqual(body, b"\x00\x01\x00\x01\x00")

    def test_register_publish_pipeline(self):
        self.connect()
        self.register()
        # Flags 0; topic id 1; msg id 0; corpo '25.5'.
        self.handler.handle(pack(Type.PUBLISH, b"\x00\x00\x01\x00\x00" + b"25.5"), self.addr)
        self.assertEqual(self.published, [("iot/sala/temperatura", b"25.5")])

    def test_multiple_topics(self):
        self.connect()
        topics = ["iot/sala/temperatura", "iot/sala/umidade", "iot/sala/presenca"]
        for msg_id, topic in enumerate(topics, 1):
            body = b"\x00\x00" + msg_id.to_bytes(2, "big") + topic.encode()
            self.handler.handle(pack(Type.REGISTER, body), self.addr)
            self.assertEqual(self.sent[-1][0][0], Type.REGACK)
        for topic_id, payload in enumerate((b"24.0", b"65", b"OFF"), 1):
            packet = b"\x00" + topic_id.to_bytes(2, "big") + b"\x00\x00" + payload
            self.handler.handle(pack(Type.PUBLISH, packet), self.addr)
        self.assertEqual(self.published, list(zip(topics, (b"24.0", b"65", b"OFF"))))

    def test_no_register_from_unknown_client(self):
        self.handler.handle(pack(Type.REGISTER, b"\x00\x00\x00\x02iot/sala/temperatura"), self.addr)
        self.assertEqual(self.sent[-1][0], (Type.REGACK, b"\x00\x00\x00\x02\x03"))

    def test_blocks_discovery_topic_spoof(self):
        self.connect()
        self.handler.handle(pack(Type.REGISTER, b"\x00\x00\x00\x02homeassistant/sensor/foo/config"), self.addr)
        self.assertEqual(self.sent[-1][0][1][-1], REJECTED_NOT_SUPPORTED)

    def test_qos1_not_supported(self):
        self.connect()
        self.register()
        self.handler.handle(pack(Type.PUBLISH, b"\x20\x00\x01\x00\x01" + b"26.0"), self.addr)
        self.assertEqual(self.published, [])
        self.assertEqual(self.sent[-1][0], (Type.PUBACK, b"\x00\x01\x00\x01\x03"))

    def test_ping_and_disconnect(self):
        self.connect()
        self.handler.handle(pack(Type.PINGREQ), self.addr)
        self.assertEqual(self.sent[-1][0], (Type.PINGRESP, b""))
        self.handler.handle(pack(Type.DISCONNECT), self.addr)
        self.assertEqual(self.sent[-1][0], (Type.DISCONNECT, b""))
        self.assertNotIn(self.addr, self.handler.sessions)


if __name__ == "__main__":
    unittest.main()
