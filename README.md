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

Verificar se o mosquitto já existe na máquina, se Sim pare o serviço:

```bash
sudo systemctl status mosquitto
sudo systemctl stop mosquitto
```
## Passo 2 — Subir o ambiente

Na pasta que contém `compose.yaml`:

```bash
docker compose config
docker compose up -d --build
docker compose ps
```
Se quiser remover o ambiente:

```bash
docker compose down -v --rmi all
```

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
4. Acesse o MQTT e a aba de Sensores.

## Passo 5 — Testes e evidências

Comandos para análise de Resultados:

```bash
docker compose logs -f publisher
docker compose logs -f gateway
docker compose exec mosquitto mosquitto_sub -h 127.0.0.1 -t 'iot/#' -v
docker compose exec mosquitto mosquitto_sub -h 127.0.0.1 -t 'iot/sala/presença' -v
```

Analisar no Wireshark as mensagens:

Filtro: 

***udp.port == 1884 or tcp.port == 1883 or tcp.port == 8123***

***Ver mensagens MQTT-SN:***

1. Acessar a aba superior com o nome ***Analyze***.
2. Acessar a aba ***Decode as***.
3. Adicionar o filtro ***Field(udp port) - Port(1884) - Current(MQTT-SN)*** 

