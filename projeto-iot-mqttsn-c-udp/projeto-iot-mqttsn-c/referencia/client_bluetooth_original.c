```
#define _GNU_SOURCE

#include <arpa/inet.h>
#include <bluetooth/bluetooth.h>
#include <bluetooth/rfcomm.h>
#include <errno.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#define MQTT_SN_CONNECT       0x04
#define MQTT_SN_CONNACK       0x05
#define MQTT_SN_REGISTER      0x0A
#define MQTT_SN_REGACK        0x0B
#define MQTT_SN_PUBLISH       0x0C
#define MQTT_SN_PUBACK        0x0D
#define MQTT_SN_DISCONNECT    0x18

#define MQTT_SN_ACCEPTED      0x00
#define MQTT_SN_REJ_CONG      0x01
#define MQTT_SN_REJ_INV_TID   0x02
#define MQTT_SN_REJ_NOTSUP    0x03

#define MAX_PACKET 4096
#define DEFAULT_KEEPALIVE 60
#define DEFAULT_TOPIC "test/topic"
#define DEFAULT_MESSAGE "hello from MQTT-SN Bluetooth client"
#define DEFAULT_CLIENT_ID "bt-client"
#define DEFAULT_RFCOMM_CHANNEL 1

static void die(const char *msg)
{
    perror(msg);
    exit(EXIT_FAILURE);
}

static void print_hex(const char *direction, const uint8_t *buf, size_t len)
{
    printf("%s MQTT-SN: %zu bytes\n  HEX:", direction, len);
    for (size_t i = 0; i < len; ++i)
        printf(" %02X", buf[i]);
    putchar('\n');
}

static int write_all(int fd, const uint8_t *buf, size_t len)
{
    size_t off = 0;
    while (off < len) {
        ssize_t n = write(fd, buf + off, len - off);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            return -1;
        }
        if (n == 0)
            return -1;
        off += (size_t)n;
    }
    return 0;
}

static int read_all(int fd, uint8_t *buf, size_t len)
{
    size_t off = 0;
    while (off < len) {
        ssize_t n = read(fd, buf + off, len - off);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            return -1;
        }
        if (n == 0)
            return 0;
        off += (size_t)n;
    }
    return 1;
}

/* MQTT-SN length field:
 *   first octet != 0x01: one-byte length
 *   first octet == 0x01: 0x01 + two-byte big-endian total length
 */
static int recv_mqttsn_frame(int fd, uint8_t *buf, size_t cap, size_t *out_len)
{
    uint8_t first;

    int rc = read_all(fd, &first, 1);
    if (rc <= 0)
        return rc;

    size_t header_len;
    size_t total_len;

    if (first == 0x01) {
        uint8_t ext[2];
        rc = read_all(fd, ext, sizeof(ext));
        if (rc <= 0)
            return rc;

        total_len = ((size_t)ext[0] << 8) | ext[1];
        header_len = 3;

        if (total_len < header_len || total_len > cap)
            return -2;

        buf[0] = first;
        buf[1] = ext[0];
        buf[2] = ext[1];
    } else {
        total_len = first;
        header_len = 1;

        if (total_len < 2 || total_len > cap)
            return -2;

        buf[0] = first;
    }

    if (read_all(fd, buf + header_len, total_len - header_len) <= 0)
        return 0;

    *out_len = total_len;
    return 1;
}

static int send_packet(int fd, uint8_t *packet, size_t len, const char *name)
{
    print_hex("TX", packet, len);
    printf("  %s\n", name);
    return write_all(fd, packet, len);
}

static int wait_for_type(int fd, uint8_t expected_type, uint8_t *packet,
                         size_t cap, size_t *packet_len)
{
    for (;;) {
        int rc = recv_mqttsn_frame(fd, packet, cap, packet_len);
        if (rc <= 0)
            return rc;

        print_hex("RX", packet, *packet_len);

        size_t type_offset = (packet[0] == 0x01) ? 3 : 1;
        uint8_t type = packet[type_offset];

        if (type == expected_type)
            return 1;

        printf("Ignoring unexpected MQTT-SN packet type 0x%02X, waiting for 0x%02X\n",
               type, expected_type);
    }
}

static size_t make_connect(uint8_t *buf, size_t cap, const char *client_id,
                           uint16_t duration)
{
    size_t id_len = strlen(client_id);
    size_t total_len = 6 + id_len;

    if (id_len == 0 || id_len > 23 || total_len > 255 || total_len > cap)
        return 0;

    buf[0] = (uint8_t)total_len;
    buf[1] = MQTT_SN_CONNECT;
    buf[2] = 0x04; /* CleanSession */
    buf[3] = 0x01; /* MQTT-SN protocol ID 1.2 */
    buf[4] = (uint8_t)(duration >> 8);
    buf[5] = (uint8_t)(duration & 0xFF);
    memcpy(buf + 6, client_id, id_len);

    return total_len;
}

static size_t make_register(uint8_t *buf, size_t cap, const char *topic,
                            uint16_t msg_id)
{
    size_t topic_len = strlen(topic);
    size_t total_len = 6 + topic_len;

    if (topic_len == 0 || total_len > 255 || total_len > cap)
        return 0;

    buf[0] = (uint8_t)total_len;
    buf[1] = MQTT_SN_REGISTER;
    buf[2] = 0x00; /* TopicId assigned by gateway */
    buf[3] = 0x00;
    buf[4] = (uint8_t)(msg_id >> 8);
    buf[5] = (uint8_t)(msg_id & 0xFF);
    memcpy(buf + 6, topic, topic_len);

    return total_len;
}

static size_t make_publish_qos0(uint8_t *buf, size_t cap, uint16_t topic_id,
                                const uint8_t *payload, size_t payload_len)
{
    size_t total_len = 7 + payload_len;

    if (total_len > 255 || total_len > cap)
        return 0;

    buf[0] = (uint8_t)total_len;
    buf[1] = MQTT_SN_PUBLISH;
    buf[2] = 0x00; /* DUP=0, QoS=0, RETAIN=0, TopicIdType=0 */
    buf[3] = (uint8_t)(topic_id >> 8);
    buf[4] = (uint8_t)(topic_id & 0xFF);
    buf[5] = 0x00; /* MsgId = 0 for QoS 0 */
    buf[6] = 0x00;
    memcpy(buf + 7, payload, payload_len);

    return total_len;
}

static size_t make_disconnect(uint8_t *buf, size_t cap)
{
    if (cap < 2)
        return 0;
    buf[0] = 0x02;
    buf[1] = MQTT_SN_DISCONNECT;
    return 2;
}

static const char *return_code_name(uint8_t rc)
{
    switch (rc) {
    case MQTT_SN_ACCEPTED:    return "Accepted";
    case MQTT_SN_REJ_CONG:    return "Rejected: congestion";
    case MQTT_SN_REJ_INV_TID: return "Rejected: invalid topic ID";
    case MQTT_SN_REJ_NOTSUP:  return "Rejected: not supported";
    default:                  return "Unknown return code";
    }
}

static int parse_connack(const uint8_t *buf, size_t len)
{
    size_t type = (buf[0] == 0x01) ? 3 : 1;
    if (len < type + 2 || buf[type] != MQTT_SN_CONNACK)
        return -1;

    uint8_t rc = buf[type + 1];
    printf("CONNACK return code: 0x%02X (%s)\n", rc, return_code_name(rc));
    return rc == MQTT_SN_ACCEPTED ? 0 : -1;
}

static int parse_regack(const uint8_t *buf, size_t len, uint16_t msg_id,
                        uint16_t *topic_id)
{
    size_t type = (buf[0] == 0x01) ? 3 : 1;
    if (len < type + 6 || buf[type] != MQTT_SN_REGACK)
        return -1;

    const uint8_t *p = buf + type + 1;
    uint16_t received_topic_id = ((uint16_t)p[0] << 8) | p[1];
    uint16_t received_msg_id = ((uint16_t)p[2] << 8) | p[3];
    uint8_t rc = p[4];

    printf("REGACK: topic_id=%u msg_id=%u return_code=0x%02X (%s)\n",
           received_topic_id, received_msg_id, rc, return_code_name(rc));

    if (received_msg_id != msg_id || rc != MQTT_SN_ACCEPTED)
        return -1;

    *topic_id = received_topic_id;
    return 0;
}

static int parse_puback(const uint8_t *buf, size_t len)
{
    size_t type = (buf[0] == 0x01) ? 3 : 1;
    if (len < type + 6 || buf[type] != MQTT_SN_PUBACK)
        return -1;

    const uint8_t *p = buf + type + 1;
    uint16_t topic_id = ((uint16_t)p[0] << 8) | p[1];
    uint16_t msg_id = ((uint16_t)p[2] << 8) | p[3];
    uint8_t rc = p[4];

    printf("PUBACK: topic_id=%u msg_id=%u return_code=0x%02X (%s)\n",
           topic_id, msg_id, rc, return_code_name(rc));
    return rc == MQTT_SN_ACCEPTED ? 0 : -1;
}

static int connect_bluetooth(const char *mac, int channel)
{
    int fd = socket(AF_BLUETOOTH, SOCK_STREAM, BTPROTO_RFCOMM);
    if (fd < 0)
        die("socket(AF_BLUETOOTH)");

    struct sockaddr_rc addr = {0};
    addr.rc_family = AF_BLUETOOTH;
    addr.rc_channel = (uint8_t)channel;

    if (str2ba(mac, &addr.rc_bdaddr) != 0) {
        fprintf(stderr, "Invalid Bluetooth MAC address: %s\n", mac);
        close(fd);
        return -1;
    }

    printf("Connecting to Bluetooth device %s on RFCOMM channel %d...\n",
           mac, channel);

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("Bluetooth connect");
        close(fd);
        return -1;
    }

    printf("Bluetooth RFCOMM connected.\n");
    return fd;
}

static void usage(const char *prog)
{
    fprintf(stderr,
        "Usage: %s <BT-MAC> [channel] [client-id] [topic] [message]\n\n"
        "Example:\n"
        "  %s AA:BB:CC:DD:EE:FF 1 bt-client test/topic hello\n",
        prog, prog);
}

int main(int argc, char **argv)
{
    if (argc < 2 || argc > 6) {
        usage(argv[0]);
        return EXIT_FAILURE;
    }

    const char *bt_mac = argv[1];
    int channel = argc >= 3 ? atoi(argv[2]) : DEFAULT_RFCOMM_CHANNEL;
    const char *client_id = argc >= 4 ? argv[3] : DEFAULT_CLIENT_ID;
    const char *topic = argc >= 5 ? argv[4] : DEFAULT_TOPIC;
    const char *message = argc >= 6 ? argv[5] : DEFAULT_MESSAGE;

    if (channel < 1 || channel > 30) {
        fprintf(stderr, "Invalid RFCOMM channel: %d\n", channel);
        return EXIT_FAILURE;
    }

    signal(SIGPIPE, SIG_IGN);

    int bt_fd = connect_bluetooth(bt_mac, channel);
    if (bt_fd < 0)
        return EXIT_FAILURE;

    uint8_t tx[MAX_PACKET];
    uint8_t rx[MAX_PACKET];
    size_t tx_len;
    size_t rx_len;

    /* 1. CONNECT */
    tx_len = make_connect(tx, sizeof(tx), client_id, DEFAULT_KEEPALIVE);
    if (tx_len == 0) {
        fprintf(stderr, "Could not create CONNECT packet.\n");
        close(bt_fd);
        return EXIT_FAILURE;
    }

    if (send_packet(bt_fd, tx, tx_len, "CONNECT") < 0) {
        perror("write CONNECT");
        close(bt_fd);
        return EXIT_FAILURE;
    }

    int rc = wait_for_type(bt_fd, MQTT_SN_CONNACK, rx, sizeof(rx), &rx_len);
    if (rc <= 0 || parse_connack(rx, rx_len) != 0) {
        fprintf(stderr, "CONNECT/CONNACK failed.\n");
        close(bt_fd);
        return EXIT_FAILURE;
    }

    /* 2. REGISTER topic */
    uint16_t register_msg_id = 1;
    tx_len = make_register(tx, sizeof(tx), topic, register_msg_id);
    if (tx_len == 0) {
        fprintf(stderr, "Could not create REGISTER packet.\n");
        close(bt_fd);
        return EXIT_FAILURE;
    }

    if (send_packet(bt_fd, tx, tx_len, "REGISTER") < 0) {
        perror("write REGISTER");
        close(bt_fd);
        return EXIT_FAILURE;
    }

    rc = wait_for_type(bt_fd, MQTT_SN_REGACK, rx, sizeof(rx), &rx_len);
    if (rc <= 0) {
        fprintf(stderr, "No REGACK received.\n");
        close(bt_fd);
        return EXIT_FAILURE;
    }

    uint16_t topic_id = 0;
    if (parse_regack(rx, rx_len, register_msg_id, &topic_id) != 0) {
        fprintf(stderr, "REGISTER rejected or malformed REGACK.\n");
        close(bt_fd);
        return EXIT_FAILURE;
    }

    /* 3. PUBLISH QoS 0 */
    tx_len = make_publish_qos0(tx, sizeof(tx), topic_id,
                               (const uint8_t *)message, strlen(message));
    if (tx_len == 0) {
        fprintf(stderr, "Could not create PUBLISH packet.\n");
        close(bt_fd);
        return EXIT_FAILURE;
    }

    if (send_packet(bt_fd, tx, tx_len, "PUBLISH QoS 0") < 0) {
        perror("write PUBLISH");
        close(bt_fd);
        return EXIT_FAILURE;
    }

    /* QoS 0 has no mandatory PUBACK. Give the forwarder/gateway a moment. */
    usleep(200000);

    /* 4. DISCONNECT */
    tx_len = make_disconnect(tx, sizeof(tx));
    if (tx_len > 0 && send_packet(bt_fd, tx, tx_len, "DISCONNECT") < 0)
        perror("write DISCONNECT");

    close(bt_fd);
    printf("MQTT-SN client finished.\n");
    return EXIT_SUCCESS;
```