## Estrutura e descrição dos arquivos

O projeto utiliza contêineres Docker para simular um ambiente IoT com sensores que se comunicam utilizando MQTT-SN. Os dados são encaminhados por um gateway MQTT-SN para um broker MQTT (Mosquitto), permitindo sua visualização no Home Assistant.

### 1. Serviços Docker

O arquivo `compose.yaml` é responsável por criar, configurar e gerenciar os cinco serviços que compõem o laboratório.

| Serviço | Descrição |
|---|---|
| **publisher** | Simula os sensores e envia seus dados utilizando o protocolo MQTT-SN sobre UDP. |
| **gateway** | Recebe as mensagens MQTT-SN dos sensores e encaminha os dados utilizando MQTT. |
| **mosquitto** | Atua como broker MQTT, recebendo e distribuindo mensagens aos clientes inscritos nos tópicos. |
| **subscriber** | Cliente MQTT responsável por receber e exibir as mensagens publicadas no broker. |
| **homeassistant** | Plataforma utilizada para monitorar e visualizar graficamente os dados dos sensores. |

### 2. Descrição dos arquivos

Os arquivos do projeto estão organizados conforme suas responsabilidades.

| Arquivo | Descrição |
|---|---|
| `compose.yaml` | Define e configura os serviços Docker utilizados no laboratório. |
| `publisher/publisher.py` | Simula os sensores e realiza a publicação dos dados utilizando MQTT-SN sobre UDP. |
| `publisher/Dockerfile` | Define as instruções necessárias para construir a imagem Docker do publisher. |
| `shared/mqttsn.py` | Implementa as funções de codificação e decodificação das mensagens MQTT-SN. |
| `gateway/gateway.py` | Recebe, interpreta e encaminha as mensagens MQTT-SN para o broker utilizando MQTT. |
| `gateway/gateway.ini` | Armazena as configurações de comunicação e os tópicos utilizados pelo gateway. |
| `gateway/requirements.txt` | Define as dependências Python necessárias para executar o gateway. |
| `gateway/Dockerfile` | Define as instruções necessárias para construir a imagem Docker do gateway. |
| `mosquitto/mosquitto.conf` | Configura o broker Mosquitto, incluindo a porta de comunicação, persistência e registros de execução. |
| `homeassistant/config/configuration.yaml` | Contém a configuração inicial do Home Assistant. |
| `tests/test_lab.py` | Executa testes das funções MQTT-SN e do processamento das mensagens pelo gateway. |
| `tests/test_udp_end_to_end.py` | Verifica a comunicação MQTT-SN sobre UDP entre o publisher e o gateway. |
| `.dockerignore` | Define os arquivos e diretórios que devem ser ignorados durante a construção das imagens Docker. |
| `README.md` | Apresenta a documentação, a estrutura e as instruções de execução do projeto. |

### 3. Principais arquivos da comunicação MQTT-SN

O funcionamento da comunicação MQTT-SN está concentrado em três arquivos principais:

**`publisher/publisher.py` — Publicação dos dados**

Responsável por simular os valores dos sensores, estabelecer a comunicação com o gateway, registrar os tópicos e publicar periodicamente os dados utilizando MQTT-SN sobre UDP.

**`shared/mqttsn.py` — Implementação das mensagens MQTT-SN**

Contém as funções utilizadas para construir e interpretar as mensagens do protocolo MQTT-SN, incluindo os campos de comprimento, tipo de mensagem e conteúdo.

Esse módulo é compartilhado entre o publisher e o gateway.

**`gateway/gateway.py` — Integração MQTT-SN/MQTT**

Responsável por receber os datagramas UDP contendo mensagens MQTT-SN, identificar os tópicos registrados e encaminhar os valores ao broker Mosquitto utilizando MQTT.

Também publica as configurações de descoberta dos sensores para integração com o Home Assistant.

### 4. Fluxo de comunicação

O fluxo de comunicação entre os componentes ocorre da seguinte maneira:

```text
Sensores simulados
       |
       v
Publisher (publisher.py)
       |
       | MQTT-SN / UDP - Porta 1884
       v
Gateway (gateway.py)
       |
       | MQTT / TCP - Porta 1883
       v
Broker Mosquitto
       |
       +------------------+
       |                  |
       v                  v
   Subscriber        Home Assistant
       |                  |
       v                  v
   Terminal           Dashboard
```

O publisher gera os dados dos sensores e os transmite ao gateway utilizando MQTT-SN. O gateway interpreta as mensagens recebidas e publica seus conteúdos no broker Mosquitto utilizando MQTT.

O broker distribui as mensagens aos clientes inscritos nos respectivos tópicos, permitindo o acompanhamento dos valores pelo subscriber e sua visualização no Home Assistant.
