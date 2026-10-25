# Laboratório IoT: temperatura, umidade e presença por MQTT-SN

Este projeto Docker Compose simula três sensores **MQTT-SN** em um contêiner publisher. O gateway recebe os datagramas UDP, decodifica `CONNECT`, `REGISTER`, `PUBLISH` (QoS 0), e publica no broker MQTT Mosquitto. Um subscriber imprime as leituras e o Home Assistant cria três entidades automaticamente com MQTT Discovery.

**Nota:** nenhum valor vem de hardware real. As medidas são calculadas no `publisher/publisher.py`.

## Arquitetura

```text
publisher (Python: temperatura / umidade / presença)
          | MQTT-SN, UDP 1884
          v
      gateway (Python)
          | MQTT, TCP 1883
          v
       mosquitto
          |             |
          v             v
     subscriber     Home Assistant (:8123)
```

| Serviço | Papel | Arquivos |
|---|---|---|
| `publisher` | Calcula e envia três leituras, registra 3 tópicos MQTT-SN | `publisher/publisher.py`, `publisher/Dockerfile` |
| `gateway` | Lê datagramas MQTT-SN, repassa ao MQTT, publica configurações Discovery | `gateway/gateway.py`, `gateway/gateway.ini`, `gateway/Dockerfile` |
| `mosquitto` | Broker TCP MQTT | `mosquitto/mosquitto.conf` |
| `subscriber` | Exibe tudo que recebe no MQTT em `iot/#` | `compose.yaml` |
| `homeassistant` | Interface e visualização dos três dispositivos | `homeassistant/config/configuration.yaml` |

### Dados e tópicos

| Entidade | Topic MQTT-SN/MQTT | Valores possíveis | Tipo Home Assistant |
|---|---|---|---|
| Temperatura | `iot/sala/temperatura` | `23.0`, `23.3` etc. | `sensor`, `temperature`, °C |
| Umidade | `iot/sala/umidade` | `45`, `48`, `51` etc. | `sensor`, `humidity`, % |
| Presença | `iot/sala/presenca` | `ON`, `OFF` | `binary_sensor`, `occupancy` |

O publisher cria uma sessão com o gateway (`CONNECT` → `CONNACK`), registra cada tópico (`REGISTER` → `REGACK`) e envia três datagramas `PUBLISH` a cada 3 segundos. Os valores são simulados assim:

```python
temperature = 23.0 + 0.3 * (seq % 14)
humidity = 45 + (seq * 3) % 30
presence = "ON" if seq % 8 < 3 else "OFF"
```

## Passo 1 — Pré-requisitos

Docker e o plugin Compose instalados e ativos:

```bash
docker --version
docker compose version
```

O projeto usa cinco contêineres. A porta `8123` do Home Assistant é publicada apenas em `127.0.0.1` (acesso no computador Docker). A porta `1884/udp` do gateway também é publicada somente no loopback local. **A porta 1883 do Mosquitto não é exposta no host:** os outros contêineres se conectam a `mosquitto:1883` dentro da rede Docker, evitando conflito com um Mosquitto já instalado no Ubuntu. Não use `localhost` como host MQTT dentro do Home Assistant.

## Passo 2 — Subir o ambiente

Na pasta que contém `compose.yaml`:

```bash
docker compose config
docker compose up -d --build
docker compose ps
```

Se estiver substituindo uma versão anterior deste laboratório, recrie os contêineres (sem apagar os volumes):

```bash
docker compose up -d --build --force-recreate
```

**Atenção:** não use `docker compose down -v`: isso removeria o volume persistente do Mosquitto. O Home Assistant usa a pasta `homeassistant/config` no host e não deve ser apagada.

## Passo 3 — Verificar publicações MQTT-SN e MQTT

Para ver os sensores gerando dados MQTT-SN:

```bash
docker compose logs -f publisher
```

Esperado (valores ilustrativos):

```text
REGACK aceito topico=iot/sala/temperatura topicId=1
REGACK aceito topico=iot/sala/umidade topicId=2
REGACK aceito topico=iot/sala/presenca topicId=3
PUBLISH MQTT-SN topico=iot/sala/temperatura valor=23.0 °C
PUBLISH MQTT-SN topico=iot/sala/umidade valor=45 %
PUBLISH MQTT-SN topico=iot/sala/presenca valor=ON
```

Verifique a conversão:

```bash
docker compose logs -f gateway
```

Esperado:

```text
PUBLISH MQTT-SN -> MQTT topico=iot/sala/umidade mensagem=45
PUBLISH MQTT-SN -> MQTT topico=iot/sala/presenca mensagem=ON
```

Verifique se o subscriber recebeu as mensagens MQTT:

```bash
docker compose logs -f subscriber
```

Esperado:

```text
iot/sala/temperatura 23.0
iot/sala/umidade 45
iot/sala/presenca ON
```

Alternativamente, obtenha apenas um resultado de cada tópico a partir do contêiner broker:

```bash
docker compose exec mosquitto mosquitto_sub -h localhost -t 'iot/#' -v -C 3
```

Os valores são retidos no broker; assim, três publicações em `iot/#` geralmente chegam de imediato.

## Passo 4 — Home Assistant

1. Abra **http://localhost:8123** no navegador do notebook que roda o Docker.
2. Em **Configurações > Dispositivos e serviços > Adicionar integração > MQTT**, conecte ao broker `mosquitto` na porta `1883`, sem usuário e sem senha (somente para laboratório).
3. Confirme que a descoberta MQTT (MQTT Discovery) está habilitada.
4. Abra **MQTT > Dispositivos / Entidades** e localize **Temperatura MQTT-SN**, **Umidade MQTT-SN** e **Presença MQTT-SN**.
5. Em **Visão geral > Editar painel > Adicionar cartão**, selecione os três sensores. Para presença, o estado será ocupado/detectado (ON) ou não (OFF).

O gateway publica `homeassistant/sensor/lab_mqttsn_temperatura/config`, `homeassistant/sensor/lab_mqttsn_umidade/config` e `homeassistant/binary_sensor/lab_mqttsn_presenca/config` como mensagens MQTT retidas. Publica também `iot/sala/status = online` enquanto conectado ao broker. Por isso, as entidades são descobertas mesmo que o Home Assistant seja reiniciado depois.

## Passo 5 — Testes e evidências

Execute os testes locais (não precisam de Docker nem broker):

```bash
python3 -m unittest discover -s tests -v
```

Dez testes devem passar, incluindo um teste de tráfego UDP real na máquina local e a validação das três publicações; a parte MQTT do teste UDP é simulada. O projeto também precisa ser verificado no Docker e no painel do Home Assistant.

Para gerar algumas publicações adicionais em outro contêiner publisher:

```bash
docker compose run --rm -e COUNT=3 -e INTERVAL=1 publisher
```

Isso envia três **ciclos**, nove mensagens (três tópicos por ciclo).

Registre as evidências para o relatório:

```bash
mkdir -p evidencias
docker compose ps > evidencias/containers.txt
docker compose logs --no-color publisher gateway subscriber mosquitto > evidencias/logs.txt
sudo tcpdump -ni any -c 40 -w evidencias/mqttsn-mqtt.pcap '(udp port 1884) or (tcp port 1883)'
```

Abra o `.pcap` no Wireshark. Capture a tela do Home Assistant exibindo as três entidades. Os prints/PCAP precisam ser capturados no seu ambiente real e não estão fabricados neste pacote.

## Solução de problemas

Se aparecer `Unable to connect (Lookup error)` ao conectar o broker MQTT:

```bash
docker compose ps
docker inspect laboratorio-iot-mosquitto-1 --format '{{json .NetworkSettings.Networks}}'
docker compose exec homeassistant python3 -c "import socket; print(socket.gethostbyname('mosquitto'))"
```

O resultado `Networks: {}` no Mosquitto significa que o contêiner não está conectado à rede Docker. Recrie os serviços com `docker compose up -d --build --force-recreate` e confirme que ambos estão na mesma rede; se persistir, examine `docker compose logs mosquitto` e `docker network inspect laboratorio-iot_default`. O nome `mosquitto` é um DNS **interno da rede Docker**, não um nome do host Ubuntu.

Se o subscriber apresentar erros, veja `docker compose logs subscriber`. Se o Mosquitto do **host** usar a porta 1883, isso não conflita com este Compose, pois a porta do broker no Docker não está publicada no host.

## Parar e reiniciar

```bash
docker compose stop              # para

docker compose start             # retoma

docker compose down              # remove contêineres, mantém volumes
```

O gateway é uma implementação **didática e parcial** do MQTT-SN 1.2. Não oferece QoS 1/2 de publicação, WILL, descoberta de gateway completa, segurança TLS, assinatura MQTT-SN nem comandos de volta ao dispositivo. O sensor de presença simulado é somente leitura. Não use estes componentes como gateway de produção.
