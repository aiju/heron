; sha256: SHA-256 (FIPS 180-4) of four fixed strings and of a generated
; 1000-byte message (byte i = (7*i + 3) & 255). Prints one lowercase hex
; digest per line.
;
; The 64 rounds keep the eight working variables a..h in r1-r8 and rotate
; them with MOVs at the end of each round (no unrolling, so the loop stays
; small). The rotate counts are chained so that each ROR starts from the
; previous result: Sigma1 rotates by 25, 18, 27 (= 25, 11, 6) instead of
; 6, 11, 25, which takes 11 shift steps instead of 18.

        .include "lib/start.s"


main:   PUSH r8
        ; Generate the 1000-byte message.
        LEA  r1, msg1000
        LEA  r2, [r1 + 1000]
        MVI  r3, 3
.gen:   STB  r3, [r1]           ; only the low byte is stored: & 255 is free
        ADDI r3, 7
        ADDI r1, 1
        CMP  r1, r2
        BNE  .gen
        ; Hash every message in the table.
        LEA  r8, messages
.next:  LD   r1, [r8]           ; message address, 0 ends the table
        BEQ  .done
        LD   r2, [r8 + 4]       ; length in bytes
        BSR  sha256
        BSR  print_digest
        ADDI r8, 8
        BRA  .next
.done:  POP  r8
        RET

; sha256: r1 = message, r2 = length in bytes -> digest in H.
; Hashes the whole 64-byte blocks in place, then builds the padded last
; block (or two) in pad. Clobbers r1-r7.
sha256:
        SAVE r8-r11
        MOV  r8, r1             ; r8 = next unhashed byte
        MOV  r9, r2             ; r9 = bytes left
        MOV  r10, r2            ; r10 = total length
        LEA  r1, H0             ; H = H0
        LEA  r2, H
        LEA  r3, [r1 + 32]
.init:  LD   r4, [r1]
        ST   r4, [r2]
        ADDI r1, 4
        ADDI r2, 4
        CMP  r1, r3
        BNE  .init
.full:  CMP  r9, #64            ; whole blocks straight from the message
        BLO  .tail
        MOV  r1, r8
        BSR  sha256_block
        ADDI r8, 64
        ADDI r9, -64
        BRA  .full
.tail:  LEA  r11, pad           ; clear both pad blocks
        MOV  r1, r11
        LEA  r2, [r11 + 128]
.clr:   ST   r0, [r1]
        ADDI r1, 4
        CMP  r1, r2
        BNE  .clr
        MOV  r1, r11            ; copy the r9 (< 64) bytes that are left
        TST  r9, r9
        BEQ  .mark
.copy:  LDB  r2, [r8]
        STB  r2, [r1]
        ADDI r8, 1
        ADDI r1, 1
        ADDI r9, -1
        BNE  .copy
.mark:  MVI  r2, -128           ; 0xFFFFFF80: STB stores the 0x80 marker
        STB  r2, [r1]
        ; The bit length goes in the last 8 bytes of the last block: one
        ; block if the marker is before byte 56, else two. The length is
        ; under 2^32 bits, so the first four of those bytes stay 0.
        LEA  r2, [r11 + 60]
        SUB  r1, r11
        CMP  r1, #56
        BLO  .len
        ADDI r2, 64
.len:   MOV  r3, r10
        LSL  r3, #3             ; bytes -> bits
        STB  r3, [r2 + 3]       ; big-endian: lowest byte last
        LSR  r3, #8
        STB  r3, [r2 + 2]
        LSR  r3, #8
        STB  r3, [r2 + 1]
        LSR  r3, #8
        STB  r3, [r2]
        MOV  r9, r2             ; r9 = start of the length field
        MOV  r8, r11
.last:  MOV  r1, r8             ; hash the one or two pad blocks
        BSR  sha256_block
        ADDI r8, 64
        CMP  r8, r9
        BLO  .last
        RESTORE r8-r11
        RET

; sha256_block: r1 = 64-byte block (any alignment) -> H updated.
; Clobbers r1-r7, saves r8-r14.
sha256_block:
        SAVE r8-r14
        ; W[0..15] = the block read as big-endian words.
        LEA  r2, W
        LEA  r3, [r2 + 64]
.load:  LDB  r4, [r1]
        LDB  r5, [r1 + 1]
        LSL  r4, #8
        OR   r4, r5
        LDB  r5, [r1 + 2]
        LSL  r4, #8
        OR   r4, r5
        LDB  r5, [r1 + 3]
        LSL  r4, #8
        OR   r4, r5
        ST   r4, [r2]
        ADDI r1, 4
        ADDI r2, 4
        CMP  r2, r3
        BNE  .load
        ; W[16..63]. r9 points at W[t-16], so W[t-15], W[t-7] and W[t-2]
        ; are all within reach of the one-parcel load (offsets 0-60).
        LEA  r9, W
        LEA  r10, [r9 + 192]    ; r9 stops at W[48] (t = 64)
.sched: LD   r1, [r9 + 4]       ; x = W[t-15]
        MOV  r2, r1
        ROR  r2, #18
        MOV  r3, r2
        ROR  r3, #21            ; 18 + 21 = 39: ROR 7
        XOR  r2, r3
        LSR  r1, #3
        XOR  r1, r2             ; r1 = s0 = ROR7 ^ ROR18 ^ SHR3
        LD   r2, [r9 + 56]      ; y = W[t-2]
        MOV  r3, r2
        ROR  r3, #17
        MOV  r4, r3
        ROR  r4, #2             ; ROR 19
        XOR  r3, r4
        LSR  r2, #10
        XOR  r2, r3             ; r2 = s1 = ROR17 ^ ROR19 ^ SHR10
        ADD  r1, r2
        LD   r2, [r9]           ; + W[t-16]
        ADD  r1, r2
        LD   r2, [r9 + 36]      ; + W[t-7]
        ADD  r1, r2
        ST   r1, [r9 + 64]      ; W[t] (offset 64: the two-parcel form)
        ADDI r9, 4
        CMP  r9, r10
        BNE  .sched
        ; a..h = H
        LEA  r13, H
        LD   r1, [r13]
        LD   r2, [r13 + 4]
        LD   r3, [r13 + 8]
        LD   r4, [r13 + 12]
        LD   r5, [r13 + 16]
        LD   r6, [r13 + 20]
        LD   r7, [r13 + 24]
        LD   r8, [r13 + 28]
        ; 64 rounds. r12 counts from -256 up to 0 in steps of 4 and indexes
        ; K and W from their ends, so ADDI sets Z on the last round.
        ; r9, r10 are temporaries.
        LI   r12, #-256
.round: MOV  r9, r5             ; T1 = h + Sigma1(e) + Ch(e,f,g) + K[t] + W[t]
        ROR  r9, #25
        MOV  r10, r9
        ROR  r10, #18           ; ROR 11
        XOR  r9, r10
        ROR  r10, #27           ; ROR 6
        XOR  r9, r10
        ADD  r8, r9             ; h += Sigma1(e)
        MOV  r9, r6             ; Ch = g ^ (e & (f ^ g))
        XOR  r9, r7
        AND  r9, r5
        XOR  r9, r7
        ADD  r8, r9
        LD   r9, [K_end + r12]
        ADD  r8, r9
        LD   r9, [W_end + r12]
        ADD  r8, r9             ; r8 = T1
        ADD  r4, r8             ; d + T1: the new e
        MOV  r9, r1             ; T2 = Sigma0(a) + Maj(a,b,c)
        ROR  r9, #2
        MOV  r10, r9
        ROR  r10, #11           ; ROR 13
        XOR  r9, r10
        ROR  r10, #9            ; ROR 22
        XOR  r9, r10
        ADD  r8, r9             ; T1 + Sigma0(a)
        MOV  r9, r1             ; Maj = (a & b) | (c & (a | b))
        OR   r9, r2
        AND  r9, r3
        MOV  r10, r1
        AND  r10, r2
        OR   r9, r10
        ADD  r9, r8             ; r9 = T1 + T2: the new a
        MOV  r8, r7             ; h g f e d c b a <- g f e d' c b a new
        MOV  r7, r6
        MOV  r6, r5
        MOV  r5, r4
        MOV  r4, r3
        MOV  r3, r2
        MOV  r2, r1
        MOV  r1, r9
        ADDI r12, 4
        BNE  .round
        ; H += a..h
        LD   r9, [r13]
        ADD  r1, r9
        ST   r1, [r13]
        LD   r9, [r13 + 4]
        ADD  r2, r9
        ST   r2, [r13 + 4]
        LD   r9, [r13 + 8]
        ADD  r3, r9
        ST   r3, [r13 + 8]
        LD   r9, [r13 + 12]
        ADD  r4, r9
        ST   r4, [r13 + 12]
        LD   r9, [r13 + 16]
        ADD  r5, r9
        ST   r5, [r13 + 16]
        LD   r9, [r13 + 20]
        ADD  r6, r9
        ST   r6, [r13 + 20]
        LD   r9, [r13 + 24]
        ADD  r7, r9
        ST   r7, [r13 + 24]
        LD   r9, [r13 + 28]
        ADD  r8, r9
        ST   r8, [r13 + 28]
        RESTORE r8-r14
        RET

; print_digest: print H as 64 lowercase hex digits and a newline.
; (print_hex in the library prints upper case.) Clobbers r1-r6.
print_digest:
        LEA  r5, H
        LEA  r6, [r5 + 32]
        LI   r4, #CONSOLE
.word:  LD   r1, [r5]
        MVI  r2, 8
.digit: ROR  r1, #28            ; rotate left 4: the next digit to bits 3-0
        MOV  r3, r1
        AND  r3, #15
        LDB  r3, [hexdigits + r3]
        STB  r3, [r4]
        ADDI r2, -1
        BNE  .digit
        ADDI r5, 4
        CMP  r5, r6
        BNE  .word
        BRA  newline            ; tail call

        .include "lib/console.s"

; ---- data ----

hexdigits:
        .ascii "0123456789abcdef"

m_empty:                        ; (zero length: the label is all it needs)
m_abc:  .ascii "abc"
m_fox:  .ascii "The quick brown fox jumps over the lazy dog"
m_two:  .ascii "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"

        .align 4
messages:                       ; address, length
        .word m_empty, 0
        .word m_abc, 3
        .word m_fox, 43
        .word m_two, 56
        .word msg1000, 1000
        .word 0

H0:     .word 0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A
        .word 0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19

K:      .word 0x428A2F98, 0x71374491, 0xB5C0FBCF, 0xE9B5DBA5
        .word 0x3956C25B, 0x59F111F1, 0x923F82A4, 0xAB1C5ED5
        .word 0xD807AA98, 0x12835B01, 0x243185BE, 0x550C7DC3
        .word 0x72BE5D74, 0x80DEB1FE, 0x9BDC06A7, 0xC19BF174
        .word 0xE49B69C1, 0xEFBE4786, 0x0FC19DC6, 0x240CA1CC
        .word 0x2DE92C6F, 0x4A7484AA, 0x5CB0A9DC, 0x76F988DA
        .word 0x983E5152, 0xA831C66D, 0xB00327C8, 0xBF597FC7
        .word 0xC6E00BF3, 0xD5A79147, 0x06CA6351, 0x14292967
        .word 0x27B70A85, 0x2E1B2138, 0x4D2C6DFC, 0x53380D13
        .word 0x650A7354, 0x766A0ABB, 0x81C2C92E, 0x92722C85
        .word 0xA2BFE8A1, 0xA81A664B, 0xC24B8B70, 0xC76C51A3
        .word 0xD192E819, 0xD6990624, 0xF40E3585, 0x106AA070
        .word 0x19A4C116, 0x1E376C08, 0x2748774C, 0x34B0BCB5
        .word 0x391C0CB3, 0x4ED8AA4A, 0x5B9CCA4F, 0x682E6FF3
        .word 0x748F82EE, 0x78A5636F, 0x84C87814, 0x8CC70208
        .word 0x90BEFFFA, 0xA4506CEB, 0xBEF9A3F7, 0xC67178F2
K_end:

H:      .space 32               ; the hash state
W:      .space 256              ; the message schedule
W_end:
pad:    .space 128              ; the padded last block(s)
msg1000:
        .space 1000
