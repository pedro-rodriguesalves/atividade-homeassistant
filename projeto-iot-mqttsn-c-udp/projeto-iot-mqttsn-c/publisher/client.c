/*
 * Cliente MQTT-SN 1.2 didatico (UDP), adaptado do client.c Bluetooth/RFCOMM.
 * Simula temperatura, umidade e presenca com CONNECT, REGISTER, PUBLISH QoS0,
 * PINGREQ/PINGRESP e DISCONNECT. Nao utiliza biblioteca MQTT comum.
 *
 * MQTT-SN packet: Length (1 octeto) | MsgType (1 octeto) | corpo.
 * O cliente utiliza somente pacotes com comprimento curto (<= 255 bytes).
 */
#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <errno.h>
#include <netdb.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#define SN_CONNECT    0x04
#define SN_CONNACK    0x05
#define SN_REGISTER   0x0A
#define SN_REGACK     0x0B
#define SN_PUBLISH    0x0C
#define SN_PINGREQ    0x16
#define SN_PINGRESP   0x17
#define SN_DISCONNECT 0x18
#define SN_ACCEPTED   0x00
#define MAX_PACKET    255
#define TOPIC_COUNT   3

static volatile sig_atomic_t running = 1;
static void stop_handler(int signo) { (void)signo; running = 0; }

typedef struct {
    const char *host;
    const char *port;
    const char *client_id;
    const char *topics[TOPIC_COUNT];
    int interval;
    int count;
    int ping_every;
    uint16_t keepalive;
} Config;

static const char *env_default(const char *name, const char *fallback) {
    const char *v = getenv(name);
    return (v && *v) ? v : fallback;
}

static int parse_int(const char *name, int default_value, int min, int max) {
    const char *s = getenv(name);
    if (!s || !*s) return default_value;
    char *end = NULL;
    errno = 0;
    long value = strtol(s, &end, 10);
    if (errno || !end || *end || value < min || value > max) {
        fprintf(stderr, "Valor invalido para %s: %s (intervalo %d..%d)\n", name, s, min, max);
        exit(EXIT_FAILURE);
    }
    return (int)value;
}

static void sleep_seconds(int seconds) {
    struct timespec req = { .tv_sec = seconds, .tv_nsec = 0 };
    while (running && nanosleep(&req, &req) < 0 && errno == EINTR) { }
}

static void print_packet(const char *direction, const char *label,
                         const uint8_t *packet, size_t size) {
    printf("%s MQTT-SN %-10s (%zu bytes) HEX:", direction, label, size);
    for (size_t i = 0; i < size; ++i) printf(" %02X", packet[i]);
    putchar('\n');
    fflush(stdout);
}

static int udp_connect(const char *host, const char *port) {
    struct addrinfo hints = {0};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_DGRAM;
    struct addrinfo *results = NULL;
    int err = getaddrinfo(host, port, &hints, &results);
    if (err != 0) {
        fprintf(stderr, "DNS do gateway: %s\n", gai_strerror(err));
        return -1;
    }
    int fd = -1;
    for (struct addrinfo *p = results; p; p = p->ai_next) {
        fd = socket(p->ai_family, p->ai_socktype, p->ai_protocol);
        if (fd < 0) continue;
        if (connect(fd, p->ai_addr, p->ai_addrlen) == 0) break;
        close(fd);
        fd = -1;
    }
    freeaddrinfo(results);
    if (fd < 0) { perror("UDP connect"); return -1; }
    struct timeval timeout = { .tv_sec = 2, .tv_usec = 0 };
    if (setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) < 0) {
        perror("SO_RCVTIMEO"); close(fd); return -1;
    }
    return fd;
}

static int send_packet(int fd, const uint8_t *packet, size_t len, const char *name) {
    print_packet("TX", name, packet, len);
    ssize_t n = send(fd, packet, len, 0);
    if (n != (ssize_t)len) {
        if (n < 0) perror("send UDP");
        else fprintf(stderr, "Envio UDP incompleto\n");
        return -1;
    }
    return 0;
}

/* Recebe um datagrama completo e valida o campo Length MQTT-SN. */
static int recv_packet(int fd, uint8_t *packet, size_t cap, uint8_t expected) {
    for (int attempt = 0; attempt < 3 && running; ++attempt) {
        ssize_t n = recv(fd, packet, cap, 0);
        if (n < 0) {
            if (errno == EINTR) continue;
            if (errno != EAGAIN && errno != EWOULDBLOCK) perror("recv UDP");
            return -1;
        }
        if (n < 2 || packet[0] != (uint8_t)n) {
            fprintf(stderr, "RX MQTT-SN: comprimento invalido (%zd)\n", n);
            continue;
        }
        print_packet("RX", "resposta", packet, (size_t)n);
        if (packet[1] == expected) return (int)n;
        fprintf(stderr, "Resposta inesperada 0x%02X (esperada 0x%02X)\n", packet[1], expected);
    }
    return -1;
}

static size_t make_connect(uint8_t *packet, const Config *cfg) {
    size_t idlen = strlen(cfg->client_id);
    if (idlen < 1 || idlen > 23) return 0;
    size_t size = 6 + idlen;
    packet[0] = (uint8_t)size;
    packet[1] = SN_CONNECT;
    packet[2] = 0x04; /* CleanSession */
    packet[3] = 0x01; /* ProtocolId: MQTT-SN 1.2 */
    packet[4] = (uint8_t)(cfg->keepalive >> 8);
    packet[5] = (uint8_t)cfg->keepalive;
    memcpy(packet + 6, cfg->client_id, idlen);
    return size;
}

static size_t make_register(uint8_t *packet, const char *topic, uint16_t msgid) {
    size_t len = strlen(topic);
    if (len < 1 || len > MAX_PACKET - 6) return 0;
    size_t size = 6 + len;
    packet[0] = (uint8_t)size;
    packet[1] = SN_REGISTER;
    packet[2] = 0; packet[3] = 0; /* Gateway atribui TopicId */
    packet[4] = (uint8_t)(msgid >> 8);
    packet[5] = (uint8_t)msgid;
    memcpy(packet + 6, topic, len);
    return size;
}

static size_t make_publish(uint8_t *packet, uint16_t topic_id, const char *payload) {
    size_t len = strlen(payload);
    if (topic_id == 0 || len > MAX_PACKET - 7) return 0;
    size_t size = 7 + len;
    packet[0] = (uint8_t)size;
    packet[1] = SN_PUBLISH;
    packet[2] = 0x00; /* DUP=0, QoS=0, RETAIN=0, TopicIdType=normal */
    packet[3] = (uint8_t)(topic_id >> 8);
    packet[4] = (uint8_t)topic_id;
    packet[5] = 0; packet[6] = 0; /* MsgId=0 para QoS0 */
    memcpy(packet + 7, payload, len);
    return size;
}

static int handshake(int fd, const Config *cfg, uint16_t topic_ids[TOPIC_COUNT]) {
    uint8_t tx[MAX_PACKET], rx[MAX_PACKET];
    size_t n = make_connect(tx, cfg);
    if (!n) { fprintf(stderr, "CLIENT_ID invalido (1..23 caracteres)\n"); return -1; }
    bool connected = false;
    for (int retry = 0; retry < 3 && running; ++retry) {
        if (send_packet(fd, tx, n, "CONNECT") < 0) return -1;
        int r = recv_packet(fd, rx, sizeof(rx), SN_CONNACK);
        if (r >= 3) {
            if (rx[2] != SN_ACCEPTED) {
                fprintf(stderr, "CONNACK rejeitado: 0x%02X\n", rx[2]);
                return -1;
            }
            connected = true;
            break;
        }
        fprintf(stderr, "CONNACK ausente; tentativa %d/3\n", retry + 1);
    }
    if (!connected) return -1;

    for (uint16_t index = 0; index < TOPIC_COUNT && running; ++index) {
        uint16_t msgid = (uint16_t)(index + 1);
        n = make_register(tx, cfg->topics[index], msgid);
        if (!n) { fprintf(stderr, "Topico MQTT-SN invalido: %s\n", cfg->topics[index]); return -1; }
        bool registered = false;
        for (int retry = 0; retry < 3 && running; ++retry) {
            if (send_packet(fd, tx, n, "REGISTER") < 0) return -1;
            int r = recv_packet(fd, rx, sizeof(rx), SN_REGACK);
            if (r == 7) {
                uint16_t topic_id = (uint16_t)(((uint16_t)rx[2] << 8) | rx[3]);
                uint16_t received_msgid = (uint16_t)(((uint16_t)rx[4] << 8) | rx[5]);
                if (received_msgid == msgid) {
                    if (rx[6] != SN_ACCEPTED || topic_id == 0) {
                        fprintf(stderr, "REGACK rejeitado para %s: 0x%02X\n", cfg->topics[index], rx[6]);
                        return -1;
                    }
                    topic_ids[index] = topic_id;
                    printf("REGACK aceito: %s -> TopicId=%u\n", cfg->topics[index], topic_id);
                    registered = true;
                    break;
                }
            }
            fprintf(stderr, "REGACK ausente/invalido para %s; tentativa %d/3\n", cfg->topics[index], retry + 1);
        }
        if (!registered) return -1;
    }
    return running ? 0 : -1;
}

static int ping_gateway(int fd) {
    uint8_t ping[] = {0x02, SN_PINGREQ};
    uint8_t rx[MAX_PACKET];
    for (int retry = 0; retry < 3 && running; ++retry) {
        if (send_packet(fd, ping, sizeof(ping), "PINGREQ") < 0) return -1;
        int n = recv_packet(fd, rx, sizeof(rx), SN_PINGRESP);
        if (n == 2) { puts("PINGRESP recebido"); return 0; }
    }
    return -1;
}

static int publish_cycle(int fd, const Config *cfg, const uint16_t ids[TOPIC_COUNT], unsigned int seq) {
    char temp[32], humidity[32];
    const char *presence = seq % 8 < 3 ? "ON" : "OFF";
    snprintf(temp, sizeof(temp), "%.1f", 23.0 + 0.3 * (seq % 14));
    snprintf(humidity, sizeof(humidity), "%u", 45 + (seq * 3) % 30);
    const char *values[TOPIC_COUNT] = {temp, humidity, presence};
    uint8_t packet[MAX_PACKET];
    for (int i = 0; i < TOPIC_COUNT && running; ++i) {
        size_t n = make_publish(packet, ids[i], values[i]);
        if (!n || send_packet(fd, packet, n, "PUBLISH") < 0) return -1;
        printf("PUBLISH MQTT-SN: topico=%s valor=%s TopicId=%u\n", cfg->topics[i], values[i], ids[i]);
    }
    return running ? 0 : -1;
}

int main(void) {
    setvbuf(stdout, NULL, _IOLBF, 0);
    signal(SIGTERM, stop_handler);
    signal(SIGINT, stop_handler);
    Config cfg = {
        .host = env_default("GATEWAY_HOST", "gateway"),
        .port = env_default("GATEWAY_PORT", "1884"),
        .client_id = env_default("CLIENT_ID", "sensores-sala-01"),
        .topics = {
            env_default("MQTT_TOPIC", "iot/sala/temperatura"),
            env_default("HUMIDITY_TOPIC", "iot/sala/umidade"),
            env_default("PRESENCE_TOPIC", "iot/sala/presenca"),
        },
        .interval = parse_int("INTERVAL", 3, 1, 600),
        .count = parse_int("COUNT", 0, 0, 1000000),
        .ping_every = parse_int("PING_EVERY", 10, 0, 1000000),
    };
    /* Duration sempre maior que o intervalo de publicacao. */
    int duration = cfg.interval * 3;
    cfg.keepalive = (uint16_t)(duration > 60 ? duration : 60);
    if (strlen(cfg.client_id) > 23 || strlen(cfg.client_id) == 0) {
        fprintf(stderr, "CLIENT_ID deve conter de 1 a 23 caracteres\n");
        return EXIT_FAILURE;
    }
    printf("Publisher MQTT-SN 1.2 (C/UDP): gateway=%s:%s interval=%ds count=%d\n",
           cfg.host, cfg.port, cfg.interval, cfg.count);

    unsigned int seq = 0;
    while (running && (cfg.count == 0 || seq < (unsigned int)cfg.count)) {
        int fd = udp_connect(cfg.host, cfg.port);
        if (fd < 0) { sleep_seconds(2); continue; }
        uint16_t topic_ids[TOPIC_COUNT] = {0};
        if (handshake(fd, &cfg, topic_ids) < 0) {
            fprintf(stderr, "Falha MQTT-SN; tentando novamente em 2 segundos...\n");
            close(fd);
            sleep_seconds(2);
            continue;
        }
        printf("Sessao MQTT-SN estabelecida; 3 topicos registrados.\n");
        unsigned int session_cycles = 0;
        while (running && (cfg.count == 0 || seq < (unsigned int)cfg.count)) {
            if (publish_cycle(fd, &cfg, topic_ids, seq) < 0) break;
            seq++;
            session_cycles++;
            if (cfg.count != 0 && seq >= (unsigned int)cfg.count) break;
            sleep_seconds(cfg.interval);
            if (cfg.ping_every > 0 && session_cycles % (unsigned int)cfg.ping_every == 0 && running) {
                if (ping_gateway(fd) < 0) {
                    fprintf(stderr, "PINGRESP ausente: reconectando ao gateway...\n");
                    break;
                }
            }
        }
        {
            const uint8_t disconnect[] = {0x02, SN_DISCONNECT};
            send_packet(fd, disconnect, sizeof(disconnect), "DISCONNECT");
        }
        close(fd);
        if (cfg.count == 0 || seq < (unsigned int)cfg.count) sleep_seconds(2);
    }
    puts("Publisher MQTT-SN encerrado.");
    return EXIT_SUCCESS;
}
