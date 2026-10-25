"""Teste real C/UDP -> gateway Python em memoria (sem Docker ou broker)."""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'shared'))
sys.path.insert(0, str(ROOT / 'gateway'))
from gateway import MQTT_SN_Handler
from mqttsn import Type, unpack


@unittest.skipUnless(shutil.which('gcc'), 'gcc nao instalado')
class PublisherCIntegrationTest(unittest.TestCase):
    def test_c_udp_handshake_register_publish_ping(self):
        with tempfile.TemporaryDirectory() as td:
            binary = str(Path(td) / 'client')
            subprocess.run([
                'gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                str(ROOT / 'publisher' / 'client.c'), '-o', binary,
            ], check=True, capture_output=True)

            server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            server.bind(('127.0.0.1', 0))
            server.settimeout(0.2)
            port = server.getsockname()[1]
            received = []
            published = []
            stop = threading.Event()

            handler = MQTT_SN_Handler(
                send=lambda packet, address: server.sendto(packet, address),
                publish=lambda topic, value: published.append((topic, value)) or True,
            )

            def gateway_loop():
                while not stop.is_set():
                    try:
                        packet, address = server.recvfrom(2048)
                    except socket.timeout:
                        continue
                    except OSError:
                        return
                    received.append(unpack(packet))
                    handler.handle(packet, address)

            thread = threading.Thread(target=gateway_loop, daemon=True)
            thread.start()
            try:
                env = os.environ.copy()
                env.update({
                    'GATEWAY_HOST': '127.0.0.1', 'GATEWAY_PORT': str(port),
                    'COUNT': '2', 'INTERVAL': '1', 'PING_EVERY': '1',
                })
                result = subprocess.run([binary], env=env, capture_output=True,
                                        text=True, timeout=18)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('03 05 00', result.stdout)  # CONNACK aceito
                self.assertIn('REGACK aceito', result.stdout)
                self.assertIn('PINGRESP recebido', result.stdout)
                self.assertEqual(len([m for m, _ in received if m == Type.CONNECT]), 1)
                self.assertEqual(len([m for m, _ in received if m == Type.REGISTER]), 3)
                self.assertEqual(len([m for m, _ in received if m == Type.PUBLISH]), 6)
                self.assertEqual(len([m for m, _ in received if m == Type.PINGREQ]), 1)
                self.assertEqual(published, [
                    ('iot/sala/temperatura', b'23.0'),
                    ('iot/sala/umidade', b'45'),
                    ('iot/sala/presenca', b'ON'),
                    ('iot/sala/temperatura', b'23.3'),
                    ('iot/sala/umidade', b'48'),
                    ('iot/sala/presenca', b'ON'),
                ])
                for kind, data in received:
                    if kind == Type.PUBLISH:
                        self.assertEqual(data[0], 0x00)  # QoS0, topic normal
                        self.assertEqual(data[3:5], b'\x00\x00')  # MsgId0
            finally:
                stop.set()
                server.close()
                thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
