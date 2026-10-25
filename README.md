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

# 6. Atividade extra — Adicionar um sensor de pressão atmosférica

Nesta atividade, será adicionado um quarto sensor ao laboratório, responsável por simular valores de pressão atmosférica.

O novo sensor utilizará:

| Propriedade | Valor |
|---|---|
| Sensor | Pressão atmosférica |
| Tópico | `iot/sala/pressao` |
| Unidade | hPa |
| Protocolo | MQTT-SN sobre UDP |
| Intervalo | 3 segundos |

Para realizar a integração, serão modificados quatro arquivos:

1. `compose.yaml`
2. `publisher/publisher.py`
3. `gateway/gateway.ini`
4. `gateway/gateway.py`

## 6.1. Modificar o arquivo `compose.yaml`

Abra o arquivo:

```bash
nano compose.yaml
```

Localize o serviço `publisher` e suas variáveis de ambiente:

```yaml
environment:
  GATEWAY_HOST: gateway
  GATEWAY_PORT: "1884"
  CLIENT_ID: sensores-sala-01
  MQTT_TOPIC: iot/sala/temperatura
  HUMIDITY_TOPIC: iot/sala/umidade
  PRESENCE_TOPIC: iot/sala/presenca
  INTERVAL: "3"
  COUNT: "0"
```

Adicione a variável:

```yaml
PRESSURE_TOPIC: iot/sala/pressao
```

O resultado será:

```yaml
environment:
  GATEWAY_HOST: gateway
  GATEWAY_PORT: "1884"
  CLIENT_ID: sensores-sala-01
  MQTT_TOPIC: iot/sala/temperatura
  HUMIDITY_TOPIC: iot/sala/umidade
  PRESENCE_TOPIC: iot/sala/presenca
  PRESSURE_TOPIC: iot/sala/pressao
  INTERVAL: "3"
  COUNT: "0"
```

Essa variável define o tópico utilizado para transmitir os valores de pressão atmosférica.

## 6.2. Modificar o arquivo `publisher/publisher.py`

Abra:

```bash
nano publisher/publisher.py
```

Localize a função:

```python
def run() -> None:
```

### Etapa 1 — Registrar o tópico

Procure:

```python
temp_topic = os.getenv("MQTT_TOPIC", "iot/sala/temperatura")
humidity_topic = os.getenv("HUMIDITY_TOPIC", "iot/sala/umidade")
presence_topic = os.getenv("PRESENCE_TOPIC", "iot/sala/presenca")

topics = [temp_topic, humidity_topic, presence_topic]
```

Substitua por:

```python
temp_topic = os.getenv("MQTT_TOPIC", "iot/sala/temperatura")
humidity_topic = os.getenv("HUMIDITY_TOPIC", "iot/sala/umidade")
presence_topic = os.getenv("PRESENCE_TOPIC", "iot/sala/presenca")
pressure_topic = os.getenv("PRESSURE_TOPIC", "iot/sala/pressao")

topics = [
    temp_topic,
    humidity_topic,
    presence_topic,
    pressure_topic
]
```

Agora o publisher registrará quatro tópicos MQTT-SN.

### Etapa 2 — Atualizar a validação

Localize:

```python
if len(set(topics)) != len(topics):
    raise ValueError("Os tres topicos MQTT-SN devem ser diferentes")
```

Substitua por:

```python
if len(set(topics)) != len(topics):
    raise ValueError("Os topicos MQTT-SN devem ser diferentes")
```

Essa validação impede que dois sensores utilizem o mesmo tópico.

### Etapa 3 — Simular a pressão atmosférica

Localize a parte do código responsável por gerar os valores dos sensores:

```python
temperature = 23.0 + 0.3 * (seq % 14)
humidity = 45 + (seq * 3) % 30
presence = "ON" if seq % 8 < 3 else "OFF"
```

Adicione:

```python
pressure = 1005.0 + 0.8 * (seq % 12)
```

O resultado será:

```python
temperature = 23.0 + 0.3 * (seq % 14)
humidity = 45 + (seq * 3) % 30
presence = "ON" if seq % 8 < 3 else "OFF"
pressure = 1005.0 + 0.8 * (seq % 12)
```

A variável `pressure` simula valores entre 1005,0 e 1013,8 hPa.

### Etapa 4 — Publicar o novo sensor

Localize as chamadas existentes da função `send_value()`.

Após a publicação do sensor de presença, adicione:

```python
send_value(
    sock,
    address,
    pressure_topic,
    topic_ids[pressure_topic],
    f"{pressure:.1f}",
    " hPa"
)
```

Essa função enviará uma mensagem MQTT-SN contendo o valor simulado da pressão atmosférica.

O tópico deverá ter sido registrado anteriormente para que o publisher possua seu `TopicId`.

### Etapa 5 — Atualizar a contagem de publicações

No final da função `run()`, localize o registro da quantidade de publicações.

Substitua a contagem fixa por:

```python
LOG.info(
    "Publisher finalizado; ciclos=%s; publicacoes=%s",
    seq,
    seq * len(topics)
)
```

Dessa maneira, o programa calculará automaticamente a quantidade de publicações com base no número de sensores.

---

## 6.3. Modificar o arquivo `gateway/gateway.ini`

Abra:

```bash
nano gateway/gateway.ini
```

Na seção `[mqtt]`, adicione:

```ini
pressure_state_topic = iot/sala/pressao
```

Esse campo identifica o tópico MQTT que receberá os valores de pressão atmosférica.

Também adicione:

```ini
pressure_discovery_topic = homeassistant/sensor/lab_mqttsn_pressao/config
```

Esse campo identifica o tópico utilizado para anunciar a nova entidade ao Home Assistant.

Não será necessário modificar a seção `[mqttsn]`, pois o prefixo `iot/` já permite o registro do novo tópico.

---

## 6.4. Modificar o arquivo `gateway/gateway.py`

Abra:

```bash
nano gateway/gateway.py
```

Localize a função:

```python
def mqtt_on_connect(self, client, userdata, flags, reason_code, properties):
```

Dentro dessa função, procure a lista:

```python
entities = [
```

Essa lista contém as configurações utilizadas pelo MQTT Discovery.

### Etapa 1 — Adicionar o sensor

Após a configuração do sensor de presença e antes do fechamento da lista, adicione:

```python
(
    mqtt_cfg["pressure_discovery_topic"],
    {
        "name": "Pressão Atmosférica MQTT-SN",
        "unique_id": "laboratorio_pressao_mqttsn_01",
        "state_topic": mqtt_cfg["pressure_state_topic"],
        "device_class": "atmospheric_pressure",
        "state_class": "measurement",
        "unit_of_measurement": "hPa",
    },
),
```

Os principais campos são:

| Campo | Função |
|---|---|
| `name` | Nome apresentado no Home Assistant. |
| `unique_id` | Identificador exclusivo da entidade. |
| `state_topic` | Tópico MQTT utilizado para receber o valor. |
| `device_class` | Classifica o sensor como pressão atmosférica. |
| `state_class` | Identifica os valores como medições. |
| `unit_of_measurement` | Define a unidade hPa. |

### Etapa 2 — Atualizar o log

Localize a mensagem de log que informa a publicação das configurações MQTT Discovery.

Substitua por:

```python
LOG.info(
    "MQTT conectado. Discovery de temperatura, "
    "umidade, presenca e pressao publicado"
)
```

Com isso, o gateway passará a anunciar quatro entidades ao Home Assistant.

---

# 7. Aplicar as alterações

Após salvar os arquivos, valide o `compose.yaml`:

```bash
docker compose config
```

Em seguida, reconstrua e recrie o publisher e o gateway:

```bash
docker compose up -d --build --force-recreate gateway publisher
```

# 9. Encerramento do ambiente

Para interromper e remover os contêineres e as redes criadas pelo Compose, execute:

```bash
docker compose down
```

Para iniciar novamente:

```bash
docker compose up -d
```

Para remover também os volumes e as imagens utilizadas pelo projeto:

```bash
docker compose down -v --rmi all
```

