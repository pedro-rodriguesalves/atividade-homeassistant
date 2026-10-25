# Laboratório IoT: publisher MQTT-SN 1.2 em C, gateway e Home Assistant

Este projeto simula **três sensores** (temperatura, umidade e presença) em um cliente **C**, adaptado de um `client.c` que utilizava **Bluetooth RFCOMM**. Nesta versão, o transporte é **UDP**. O programa **constrói pacotes MQTT-SN**; não utiliza uma biblioteca MQTT convencional para publicar os sensores.

## Arquitetura

```text
  publisher/client.c (C, UDP)
     |  CONNECT / REGISTER / PUBLISH MQTT-SN 1.2
     |  porta UDP 1884
     v
  gateway/gateway.py (Python)
     |  converte publicacoes MQTT-SN em MQTT
     |  porta TCP 1883
     v
  Mosquitto (broker MQTT)
     |                    |
     v                    v
  subscriber         Home Assistant
  (mosquitto_sub)    (painel, porta 8123)
```

**Não há Bluetooth nesta versão.** MQTT-SN é o protocolo de aplicação; UDP é o transporte. O Wireshark pode mostrar apenas UDP se não houver decodificador MQTT-SN habilitado. Incluímos um *dissector Lua* para a porta UDP 1884.

## Estrutura dos arquivos

| Caminho | Responsabilidade |
|---|---|
| `compose.yaml` | Orquestra os cinco serviços e a rede Docker. |
| `publisher/client.c` | Cliente MQTT-SN 1.2 em C; gera três sensores e publica via UDP. |
| `publisher/Dockerfile` | Compila o código C e executa o binário no contêiner. |
| `gateway/gateway.py` | Recebe CONNECT, REGISTER, PUBLISH, PINGREQ e converte os valores em MQTT. |
| `gateway/gateway.ini` | Endereço do broker, portas, tópicos e MQTT Discovery. |
| `gateway/Dockerfile`, `gateway/requirements.txt` | Preparam o gateway Python. |
| `shared/mqttsn.py` | Funções de codificação/decodificação utilizadas pelo gateway. |
| `mosquitto/mosquitto.conf` | Configura o broker MQTT na porta 1883. |
| `homeassistant/config/configuration.yaml` | Configuração básica do Home Assistant. |
| `wireshark/mqttsn_1884.lua` | Mostra os campos MQTT-SN no Wireshark. |
| `tests/test_lab.py` | Testa o protocolo e a lógica do gateway. |
| `tests/test_c_publisher.py` | Compila o cliente C e testa a comunicação UDP com um gateway Python em memória. |
| `referencia/client_bluetooth_original.c` | Código original Bluetooth do usuário, somente para comparação; não entra no build. |

## 1. Iniciar o projeto

Requer Docker Engine e `docker compose` no Ubuntu. Na pasta do projeto:

```bash
docker compose config
docker compose up -d --build
docker compose ps
```

Aguarde o Mosquitto ficar saudável e o publisher registrar os três tópicos.

**Se a versão anterior estiver em execução**, pare-a na pasta antiga com `docker compose down` (sem `-v`) antes de iniciar a nova. Este projeto usa o mesmo nome Compose `laboratorio-iot`. **O volume do Mosquitto permanece**, mas a configuração do Home Assistant está em uma pasta local. Se desejar preservar seu Home Assistant antigo, copie sua pasta `homeassistant/config/` para este projeto antes de iniciar.

Se preferir atualizar **a pasta antiga**, use o ZIP de atualização (fornecido separadamente) que substitui apenas `publisher/client.c`, `publisher/Dockerfile`, `compose.yaml` e adiciona os testes e o dissector. Não apague sua pasta de configuração do Home Assistant.

## 2. Verificar o tráfego MQTT-SN

```bash
docker compose logs -f publisher
```

Exemplo de mensagens reais geradas pelo programa (os identificadores são atribuídos pelo gateway):

```text
TX MQTT-SN CONNECT    (22 bytes) HEX: 16 04 04 01 00 3C ...
RX MQTT-SN resposta   (3 bytes) HEX: 03 05 00
TX MQTT-SN REGISTER   (...) HEX: ... 0A ...
RX MQTT-SN resposta   (7 bytes) HEX: 07 0B 00 01 00 01 00
REGACK aceito: iot/sala/temperatura -> TopicId=1
TX MQTT-SN PUBLISH    (11 bytes) HEX: 0B 0C 00 00 01 00 00 32 33 2E 30
PUBLISH MQTT-SN: topico=iot/sala/temperatura valor=23.0 TopicId=1
```

O `0x0C` é o código **MQTT-SN PUBLISH**. Um exemplo de pacote `0B 0C 00 00 01 00 00 32 33 2E 30` significa: `Length=11`, `Type=PUBLISH`, `Flags=0`, `TopicId=1`, `MsgId=0`, `Data=23.0`.

O fluxo é:

1. `CONNECT` → `CONNACK` para iniciar a sessão MQTT-SN.
2. `REGISTER` → `REGACK` para registrar **cada um dos três tópicos**.
3. `PUBLISH` (QoS 0) para enviar os valores, sem `PUBACK`.
4. `PINGREQ` → `PINGRESP` a cada 10 ciclos (configurável).
5. `DISCONNECT` ao encerrar a sessão.

**Os valores são simulados**: temperatura `23.0 + 0.3 * (seq % 14)`, umidade `45 + (seq * 3) % 30` e presença `ON` quando `seq % 8 < 3`, senão `OFF`.

## 3. Verificar a conversão MQTT-SN → MQTT

```bash
docker compose logs -f gateway
```

Exemplo:

```text
CONNECT MQTT-SN cliente=sensores-sala-01 ...
REGISTER MQTT-SN ... topico=iot/sala/temperatura
PUBLISH MQTT-SN -> MQTT topico=iot/sala/temperatura mensagem=23.0
PUBLISH MQTT-SN -> MQTT topico=iot/sala/umidade mensagem=45
PUBLISH MQTT-SN -> MQTT topico=iot/sala/presenca mensagem=ON
```

O broker distribui essas publicações a clientes inscritos. Confira:

```bash
docker compose logs -f subscriber
```

Ou:

```bash
docker compose exec mosquitto mosquitto_sub -h 127.0.0.1 -t 'iot/#' -v -C 3
```

Tópicos publicados:

| Tópico | Valor de exemplo |
|---|---|
| `iot/sala/temperatura` | `23.0` |
| `iot/sala/umidade` | `45` |
| `iot/sala/presenca` | `ON` |

## 4. Home Assistant

Abra **http://localhost:8123** no computador que executa o Docker. Em **Configurações → Dispositivos e serviços → Adicionar integração → MQTT**, configure o broker como **`mosquitto`**, porta **`1883`** (não use `localhost` dentro do Home Assistant). No laboratório, o Mosquitto aceita conexões sem usuário e senha.

O gateway publica automaticamente as configurações de descoberta (*MQTT Discovery*) para **Temperatura MQTT-SN**, **Umidade MQTT-SN** e **Presença MQTT-SN**. Adicione as entidades ao dashboard. A porta `1883` **não** é exposta no host para evitar conflito com o Mosquitto instalado no Ubuntu.

## 5. Wireshark: mostrar os campos MQTT-SN

Use o filtro:

```text
udp.port == 1884
```

No Wireshark, abra **Ajuda → Sobre o Wireshark → Pastas** e localize a pasta **Personal Lua Plugins**. Copie `wireshark/mqttsn_1884.lua` para lá e reinicie o Wireshark. O script decodifica o tráfego da porta UDP 1884 e apresenta **MQTT-SN 1.2** com `Length`, `MsgType`, `Flags`, `TopicId`, `MsgId` e `Data`.

**Atenção:** como publisher e gateway estão em contêineres Docker, os datagramas normalmente passam pela **bridge/veth Docker**; uma captura apenas na interface física Wi-Fi/Ethernet do host pode não mostrá-los. Para descobrir as interfaces:

```bash
ip -br link
sudo tcpdump -i any -nn -c 50 'udp port 1884'
```

Para capturar também MQTT/TCP (1883) e abrir no Wireshark:

```bash
sudo tcpdump -i any -nn -w mqttsn-mqtt.pcap '(udp port 1884) or (tcp port 1883)'
```

Interrompa com Ctrl+C. O Wireshark mostrará MQTT no TCP/1883 quando o tráfego não estiver criptografado. Para MQTT-SN no UDP/1884, use o decodificador incluído se necessário.

## 6. Alterar frequência e quantidade de publicações

No `compose.yaml`, seção `publisher.environment`:

- `INTERVAL: "3"`: um ciclo a cada 3 segundos; cada ciclo envia três mensagens.
- `COUNT: "0"`: repete indefinidamente; `COUNT: "5"` envia cinco ciclos (15 publicações).
- `PING_EVERY: "10"`: faz um `PINGREQ` a cada dez ciclos; `0` desativa o ping periódico.
- `CLIENT_ID`: identificador MQTT-SN (1 a 23 caracteres neste cliente).

Recrie o publisher após alterar:

```bash
docker compose up -d --build --force-recreate publisher
```

Para executar uma instância temporária com dois ciclos, pare o publisher normal para evitar duas instâncias com o mesmo ID:

```bash
docker compose stop publisher
docker compose run --rm -e COUNT=2 -e INTERVAL=1 -e PING_EVERY=1 publisher
docker compose start publisher
```

## 7. Testes

No host Ubuntu com Python 3 e GCC instalados:

```bash
python3 -m unittest discover -s tests -v
```

O teste `test_c_publisher.py` compila o cliente C e o executa **sobre UDP real no loopback**, com o gateway Python em memória. Ele verifica `CONNECT`, `REGISTER` dos três tópicos, seis `PUBLISH` em dois ciclos e `PINGREQ`/`PINGRESP`. Não depende de Docker nem de um broker MQTT.

Para compilar e testar manualmente **fora do Docker**, é necessário um gateway acessível por UDP:

```bash
gcc -std=c11 -O2 -Wall -Wextra -o mqttsn-client publisher/client.c
GATEWAY_HOST=127.0.0.1 GATEWAY_PORT=1884 COUNT=2 ./mqttsn-client
```

Esse comando usa a porta UDP publicada no loopback do host pelo Compose.

## 8. Problemas comuns

**Wireshark mostra somente UDP:** o payload ainda pode ser MQTT-SN correto; instale o dissector Lua. Verifique o campo `0x0C` após o byte de comprimento nos pacotes PUBLISH.

**Publisher não recebe CONNACK:** veja `docker compose logs gateway`; confirme a rede do Docker, a porta UDP 1884 e o nome DNS `gateway`.

**Home Assistant mostra erro de DNS ao conectar Mosquitto:** verifique `docker compose ps` e se `mosquitto` está conectado à rede do Compose. Use o nome `mosquitto` no Home Assistant, não o endereço do host.

**Gateway reinicia durante publicações:** como o publisher utiliza QoS 0, publicações podem se perder até a próxima reconexão. O ping periódico detecta a indisponibilidade em até alguns ciclos, mas não garante entrega de todas as mensagens.

## Limitações do laboratório

Este projeto implementa **um subconjunto MQTT-SN 1.2**: não suporta QoS 1/2 no publisher, WILL, DTLS, descoberta completa de gateway nem todas as extensões. Os sensores são simulados; não há hardware real. O broker está sem autenticação **apenas para uso local e isolado**.
