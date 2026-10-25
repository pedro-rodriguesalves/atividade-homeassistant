# Código de referência

`client_bluetooth_original.c` é o código C original enviado pelo usuário, que enviava quadros MQTT-SN via Bluetooth RFCOMM. Ele está aqui somente para comparação e **não é compilado pelo Docker**.

A implementação utilizada pelo projeto é `../publisher/client.c`, que mantém o formato de mensagens MQTT-SN, mas usa `AF_INET`, `SOCK_DGRAM` e UDP, além de simular três tópicos continuamente.
