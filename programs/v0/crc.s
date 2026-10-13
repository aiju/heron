; crc: CRC-16/CCITT-FALSE (poly 1021, init FFFF, no reflection, no final xor),
; bit by bit and with a 256-entry table, over "123456789" (check value 29B1)
; and over 1 KB of xorshift output.

        .include "lib/start.s"

BUFLEN = 1024

main:   PUSH r8
        PUSH r9

        BSR  mktable

        LI   r1, #0xACE1        ; 1 KB test buffer: 512 random words
        CALL srand
        LI   r8, #buffer
        LI   r9, #BUFLEN / 2
.fill:  CALL rand
        ST   r1, [r8]
        ADDI r8, 2
        DEC  r9
        BNE  .fill

        LI   r8, #tests
.test:  LD   r1, [r8]           ; label, 0 ends the list
        BEQ  .done
        CALL puts
        LD   r1, [r8 + 2]       ; data
        LD   r2, [r8 + 4]       ; length
        LI   r3, #0xFFFF
        LD   r4, [r8 + 6]       ; routine
        CALL r4
        CALL print_hex16
        CALL newline
        ADDI r8, 8
        BRA  .test
.done:  POP  r9
        POP  r8
        RET

; crc_bits: r1 = data, r2 = length, r3 = crc -> r1 = crc. One bit at a time:
; SHL puts the old bit 15 into C, which decides whether to apply the poly.
crc_bits:
        MOV  r4, r1
        MOV  r1, r3
        TST  r2, r2
        BEQ  .done
.byte:  LDB  r5, [r4]
        SWAB r5                 ; byte << 8
        XOR  r1, r5
        MVI  r6, 8
.bit:   SHL  r1
        BCC  .nopoly
        XOR  r1, #0x1021
.nopoly:
        DEC  r6
        BNE  .bit
        INC  r4
        DEC  r2
        BNE  .byte
.done:  RET

; crc_table: same arguments. crc = (crc << 8) ^ table[(crc >> 8) ^ byte]
crc_table:
        TST  r2, r2
        BEQ  .done
.byte:  LDB  r4, [r1]
        SWAB r5, r3             ; crc >> 8 is the low byte of the swapped crc
        XOR  r4, r5
        ZXT  r4
        SHL  r4                 ; word index
        ZXT  r3                 ; crc << 8
        SWAB r3
        LD   r5, [table + r4]
        XOR  r3, r5
        INC  r1
        DEC  r2
        BNE  .byte
.done:  MOV  r1, r3
        RET

; mktable: table[i] = CRC of the single byte i with crc 0.
mktable:
        LI   r3, #table
        MVI  r1, 0              ; i
.entry: SWAB r2, r1             ; i << 8
        MVI  r4, 8
.bit:   SHL  r2
        BCC  .nopoly
        XOR  r2, #0x1021
.nopoly:
        DEC  r4
        BNE  .bit
        ST   r2, [r3]
        ADDI r3, 2
        INC  r1
        CMP  r1, #256
        BNE  .entry
        RET

tests:  .word s_bits9, check, 9, crc_bits
        .word s_table9, check, 9, crc_table
        .word s_bits1k, buffer, BUFLEN, crc_bits
        .word s_table1k, buffer, BUFLEN, crc_table
        .word 0
s_bits9:   .asciz "bitwise \"123456789\": "
s_table9:  .asciz "table   \"123456789\": "
s_bits1k:  .asciz "bitwise 1 KB buffer: "
s_table1k: .asciz "table   1 KB buffer: "
check:     .ascii "123456789"

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/rand.s"

        .align 2
table:  .space 512
buffer: .space BUFLEN
