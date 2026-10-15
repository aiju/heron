; crc: CRC-16/CCITT-FALSE (poly 1021, init FFFF, no reflection, no final xor),
; bit by bit and with a 256-entry table, over "123456789" (check value 29B1)
; and over 1 KB of xorshift output (512 values from seed ACE1, stored as
; little-endian halves).
;
; The bitwise loops keep the CRC in the top half of a register: LSL #1 then
; drops its bit 15 into C, which says whether to apply the polynomial, and
; no masking is needed.

        .include "lib/start.s"

BUFLEN = 1024
POLY32 = 0x10210000             ; the polynomial, top-aligned like the CRC

main:   SAVE r7-r9
        BSR  mktable

        MOV  r1, #0xACE1        ; the 1 KB test buffer
        BSR  srand
        MOV  r8, #buffer
        MOV  r9, #BUFLEN / 2
.fill:  BSR  rand
        MOV  half [r8], r1      ; (there is no half [r]+ mode)
        ADD  r8, #2
        DBNZ r9, .fill

        LEA  r8, [tests]        ; run the four tests, walking the table with [r8]+
.test:  MOVS r1, [r8]+          ; label; 0 ends the list
        BEQ  .done
        BSR  puts
        MOV  r1, [r8]+          ; data
        MOV  r2, [r8]+          ; length
        MOV  r3, #0xFFFF        ; initial CRC
        CALL [r8]+              ; the routine
        MOV  r2, #4
        BSR  print_hex
        BSR  newline
        BRA  .test
.done:  RESTORE r7-r9
        RET

; crc_bits: r1 = data, r2 = length, r3 = CRC -> r1 = CRC, one bit at a time.
crc_bits:
        LSL  r3, #16            ; top-aligned
        MOV  r5, #POLY32
        ADD  r2, r1             ; r2 = end
        BRA  .next
.byte:  MOV  r4, byte [r1]+
        LSL  r4, #24            ; crc ^= byte << 8 (top-aligned)
        XOR  r3, r4
        MOV  r6, #8
.bit:   LSL  r3, #1
        BCC  .nopoly
        XOR  r3, r5
.nopoly:
        DBNZ r6, .bit
.next:  CMP  r1, r2
        BLO  .byte
        MOV  r1, r3
        LSR  r1, #16
        RET

; crc_table: same arguments. crc = (crc << 8) ^ table[(crc >> 8) ^ byte].
; The CRC is kept in the low half and never masked inside the loop: the bits
; that pile up above bit 15 only move further up, and the index takes just
; the low byte of crc >> 8. Both the data byte and the table entry are
; memory operands of XOR.
crc_table:
        MOV  r6, #table         ; base for the indexed mode
        ADD  r2, r1             ; r2 = end
        BRA  .next
.byte:  MOV  r4, r3
        LSR  r4, #8
        XOR  r4, byte [r1]+     ; crc >> 8 ^ byte
        ZXB  r4                 ; index
        LSL  r3, #8
        XOR  r3, half [r6 + r4*2]
.next:  CMP  r1, r2
        BLO  .byte
        ZXH  r1, r3
        RET

; mktable: table[i] = the CRC of the single byte i, starting from 0, i.e.
; i << 8 put through 8 steps of the bitwise loop. Fills it from the top down.
mktable:
        MOV  r5, #POLY32
        MOV  r3, #table
        MOV  r1, #255           ; r1 = i
.entry: MOV  r2, r1
        LSL  r2, #24            ; i << 8, top-aligned
        MOV  r4, #8
.bit:   LSL  r2, #1
        BCC  .nopoly
        XOR  r2, r5
.nopoly:
        DBNZ r4, .bit
        LSR  r2, #16
        MOV  half [r3 + r1*2], r2
        DEC  r1
        BPL  .entry
        RET

        .align 4
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

        .align 4
table:  .space 2 * 256
buffer: .space BUFLEN
