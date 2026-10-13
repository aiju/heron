/* crc: CRC-16/CCITT-FALSE bit by bit and with a 256-entry table, over
   "123456789" and over 1 KB of xorshift output. */
#include <stdio.h>

static unsigned short table[256];
static unsigned char buf[1024];

static unsigned crc_bitwise(const unsigned char *p, int n)
{
    unsigned crc = 0xffff;
    int k;
    while (n--) {
        crc ^= *p++ << 8;
        for (k = 0; k < 8; k++)
            crc = crc & 0x8000 ? (crc << 1) ^ 0x1021 : crc << 1;
    }
    return crc & 0xffff;
}

static void make_table(void)
{
    unsigned i, crc;
    int k;
    for (i = 0; i < 256; i++) {
        crc = i << 8;
        for (k = 0; k < 8; k++)
            crc = crc & 0x8000 ? (crc << 1) ^ 0x1021 : crc << 1;
        table[i] = crc;
    }
}

static unsigned crc_table(const unsigned char *p, int n)
{
    unsigned crc = 0xffff;
    while (n--)
        crc = (crc << 8 ^ table[(crc >> 8 ^ *p++) & 0xff]) & 0xffff;
    return crc;
}

int main(void)
{
    static const unsigned char digits[] = "123456789";
    unsigned x = 0xace1;
    int i;
    for (i = 0; i < 512; i++) {
        x ^= (x << 7) & 0xffff;
        x ^= x >> 9;
        x ^= (x << 8) & 0xffff;
        buf[2 * i] = x;
        buf[2 * i + 1] = x >> 8;
    }
    make_table();
    printf("bitwise \"123456789\": %04X\n", crc_bitwise(digits, 9));
    printf("table   \"123456789\": %04X\n", crc_table(digits, 9));
    printf("bitwise 1 KB buffer: %04X\n", crc_bitwise(buf, 1024));
    printf("table   1 KB buffer: %04X\n", crc_table(buf, 1024));
    return 0;
}
