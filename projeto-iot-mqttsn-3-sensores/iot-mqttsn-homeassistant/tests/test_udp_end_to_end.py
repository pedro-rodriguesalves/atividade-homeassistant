"""Teste UDP real em localhost: publisher -> gateway (com MQTT simulado)."""

import os
import socket
import subprocess
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "gateway"))

from gateway import MQTT_SN_Handler


class UdpIntegrationTest(unittest.TestCase):
    def test_three_real_udp_publications(self):
        published = []
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.bind(("127.0.0.1", 0))
        udp_socket.settimeout(0.2)
        port = udp_socket.getsockname()[1]
        quit_event = threading.Event()
        bridge = MQTT_SN_Handler(
            send=udp_socket.sendto,
            publish=lambda topic, value: published.append((topic, value)) or True,
        )

        def udp_server():
            while not quit_event.is_set():
                try:
                    packet, addr = udp_socket.recvfrom(65535)
                    bridge.handle(packet, addr)
                except socket.timeout:
                    pass
                except OSError:
                    break

        server_thread = threading.Thread(target=udp_server, daemon=True)
        server_thread.start()
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(ROOT / "shared"),
            "GATEWAY_HOST": "127.0.0.1",
            "GATEWAY_PORT": str(port),
            "COUNT": "3",
            "INTERVAL": "0.01",
            "CLIENT_ID": "teste-udp-real",
        })
        try:
            result = subprocess.run(
                [sys.executable, "-u", str(ROOT / "publisher" / "publisher.py")],
                env=env, capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertEqual(published, [
                ("iot/sala/temperatura", b"23.0"),
                ("iot/sala/umidade", b"45"),
                ("iot/sala/presenca", b"ON"),
                ("iot/sala/temperatura", b"23.3"),
                ("iot/sala/umidade", b"48"),
                ("iot/sala/presenca", b"ON"),
                ("iot/sala/temperatura", b"23.6"),
                ("iot/sala/umidade", b"51"),
                ("iot/sala/presenca", b"ON"),
            ])
        finally:
            quit_event.set()
            udp_socket.close()
            server_thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
