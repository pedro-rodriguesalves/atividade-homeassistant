"""Codificacao minima de quadros MQTT-SN 1.2 para fins didaticos.

Suporta comprimento de 1 byte e comprimento estendido (3 bytes).
Nao implementa toda a especificacao MQTT-SN.
"""

from enum import IntEnum


class Type(IntEnum):
    ADVERTISE = 0x00
    SEARCHGW = 0x01
    GWINFO = 0x02
    CONNECT = 0x04
    CONNACK = 0x05
    REGISTER = 0x0A
    REGACK = 0x0B
    PUBLISH = 0x0C
    PUBACK = 0x0D
    PINGREQ = 0x16
    PINGRESP = 0x17
    DISCONNECT = 0x18


ACCEPTED = 0x00
REJECTED_CONGESTION = 0x01
REJECTED_INVALID_TOPIC_ID = 0x02
REJECTED_NOT_SUPPORTED = 0x03


def pack(message_type: int, body: bytes = b"") -> bytes:
    """Gera um datagrama com exatamente uma mensagem MQTT-SN."""
    short_length = 2 + len(body)
    if short_length <= 255:
        return bytes([short_length, message_type]) + body
    long_length = 4 + len(body)
    if long_length > 65535:
        raise ValueError("Mensagem MQTT-SN muito grande")
    return b"\x01" + long_length.to_bytes(2, "big") + bytes([message_type]) + body


def unpack(datagram: bytes) -> tuple[int, bytes]:
    """Retorna tipo e corpo; rejeita comprimento diferente do informado."""
    if len(datagram) < 2:
        raise ValueError("Quadro MQTT-SN incompleto")
    if datagram[0] == 0x01:
        if len(datagram) < 4:
            raise ValueError("Cabecalho estendido incompleto")
        length = int.from_bytes(datagram[1:3], "big")
        if length != len(datagram) or length < 4:
            raise ValueError("Comprimento estendido invalido")
        return datagram[3], datagram[4:]
    if datagram[0] != len(datagram) or datagram[0] < 2:
        raise ValueError("Comprimento curto invalido")
    return datagram[1], datagram[2:]
