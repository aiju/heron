; sha256: SHA-256 (FIPS 180-4) of four fixed strings and of a generated
; 1000-byte message (byte i = (7*i + 3) & 255). Prints one lowercase hex
; digest per line.
;
; The 64 rounds keep the eight working variables a..h in r1-r8 and rotate
; them with MOVs at the end of each round (no unrolling, so the loop stays
; small). K[t] and W[t] are added straight from memory through two
; auto-incrementing pointers. The rotate counts are chained so that each ROR
; starts from the previous result: Sigma1 rotates by 25, 18, 27 (= 25, 11,
; 6) instead of 6, 11, 25, which takes 11 shift steps instead of 18.

        .include "lib/start.s"

main:   PUSH r8
        ; Generate the 1000-byte message.
        MOV  r1, #msg1000
        MOV  r2, #msg1000 + 1000
        MOV  r3, #3
.gen:   MOV  byte [r1]+, r3     ; only the low byte is stored: & 255 is free
        ADD  r3, #7
        CMP  r1, r2
        BNE  .gen
        ; Hash every message in the table.
        MOV  r8, #messages
.next:  MOVS r1, [r8]+          ; message address, 0 ends the table
        BEQ  .done
        MOV  r2, [r8]+          ; length in bytes
        BSR  sha256
        BSR  print_digest
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
        MOV  r1, #H0            ; H = H0
        MOV  r2, #H
        MOV  r3, #8
.init:  MOV  r4, [r1]+
        MOV  [r2]+, r4
        DBNZ r3, .init
.full:  CMP  r9, #64            ; whole blocks straight from the message
        BLO  .tail
        MOV  r1, r8
        BSR  sha256_block
        ADD  r8, #64
        SUB  r9, #64
        BRA  .full
.tail:  MOV  r11, #pad          ; clear both pad blocks
        MOV  r1, r11
        MOV  r2, #32
.clr:   CLR  [r1]+
        DBNZ r2, .clr
        MOV  r1, r11            ; copy the r9 (< 64) bytes that are left
        TST  r9, r9
        BEQ  .mark
.copy:  MOV  r2, byte [r8]+
        MOV  byte [r1]+, r2
        DBNZ r9, .copy
.mark:  MOV  r2, #0x80
        MOV  byte [r1], r2
        ; The bit length goes in the last 8 bytes of the last block: one
        ; block if the marker is before byte 56, else two. The length is
        ; under 2^32 bits, so the first four of those bytes stay 0.
        LEA  r2, [r11 + 60]
        SUB  r1, r11
        CMP  r1, #56
        BLO  .len
        ADD  r2, #64
.len:   MOV  r3, r10
        LSL  r3, #3             ; bytes -> bits
        REV  r3                 ; big-endian
        MOV  [r2]+, r3          ; (pad is word-aligned)
        MOV  r9, r2             ; r9 = end of the last block
        MOV  r8, r11
.last:  MOV  r1, r8             ; hash the one or two pad blocks
        BSR  sha256_block
        ADD  r8, #64
        CMP  r8, r9
        BLO  .last
        RESTORE r8-r11
        RET

; sha256_block: r1 = 64-byte block (any alignment) -> H updated.
; Clobbers r1-r7, saves r8-r14.
sha256_block:
        SAVE r8-r14
        ; W[0..15] = the block read as big-endian words: a word load and REV
        ; if the block is aligned (the pad blocks and msg1000's are), byte
        ; by byte if not.
        MOV  r2, #W
        TST  r1, #3
        BNE  .bytes
        MOV  r3, #16
.words: MOV  r4, [r1]+
        REV  r4
        MOV  [r2]+, r4
        DBNZ r3, .words
        BRA  .expand
.bytes: MOV  r3, #W + 64
.load:  MOV  r4, byte [r1]+
        LSL  r4, #8
        OR   r4, byte [r1]+
        LSL  r4, #8
        OR   r4, byte [r1]+
        LSL  r4, #8
        OR   r4, byte [r1]+
        MOV  [r2]+, r4
        CMP  r2, r3
        BNE  .load
        ; W[16..63]. r9 points at W[t-16]; the last add steps it on.
.expand:
        MOV  r9, #W
        MOV  r10, #W + 192      ; r9 stops at W[48] (t = 64)
.sched: MOV  r1, [r9 + 4]       ; x = W[t-15]
        MOV  r2, r1
        ROR  r2, #18
        MOV  r3, r2
        ROR  r3, #21            ; 18 + 21 = 39: ROR 7
        XOR  r2, r3
        LSR  r1, #3
        XOR  r1, r2             ; r1 = s0 = ROR7 ^ ROR18 ^ SHR3
        MOV  r2, [r9 + 56]      ; y = W[t-2]
        MOV  r3, r2
        ROR  r3, #17
        MOV  r4, r3
        ROR  r4, #2             ; ROR 19
        XOR  r3, r4
        LSR  r2, #10
        XOR  r2, r3             ; r2 = s1 = ROR17 ^ ROR19 ^ SHR10
        ADD  r1, r2
        ADD  r1, [r9 + 36]      ; + W[t-7]
        ADD  r1, [r9]+          ; + W[t-16]; r9 -> W[t-15]
        MOV  [r9 + 60], r1      ; W[t]
        CMP  r9, r10
        BNE  .sched
        ; a..h = H
        MOV  r13, #H
        MOV  r1, [r13]
        MOV  r2, [r13 + 4]
        MOV  r3, [r13 + 8]
        MOV  r4, [r13 + 12]
        MOV  r5, [r13 + 16]
        MOV  r6, [r13 + 20]
        MOV  r7, [r13 + 24]
        MOV  r8, [r13 + 28]
        ; 64 rounds. r11 walks K and r12 walks W; r14 = end of K.
        ; r9, r10 are temporaries.
        MOV  r11, #K
        MOV  r12, #W
        MOV  r14, #K_end
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
        ADD  r8, [r11]+         ; + K[t]
        ADD  r8, [r12]+         ; + W[t]: r8 = T1
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
        CMP  r11, r14
        BNE  .round
        ; H += a..h (there is no memory-destination add: add, then store)
        ADD  r1, [r13]
        MOV  [r13]+, r1
        ADD  r2, [r13]
        MOV  [r13]+, r2
        ADD  r3, [r13]
        MOV  [r13]+, r3
        ADD  r4, [r13]
        MOV  [r13]+, r4
        ADD  r5, [r13]
        MOV  [r13]+, r5
        ADD  r6, [r13]
        MOV  [r13]+, r6
        ADD  r7, [r13]
        MOV  [r13]+, r7
        ADD  r8, [r13]
        MOV  [r13]+, r8
        RESTORE r8-r14
        RET

; print_digest: print H as 64 lowercase hex digits and a newline.
; (print_hex in the library prints upper case.) Clobbers r1-r6.
print_digest:
        MOV  r5, #H
        MOV  r6, #H + 32
        MOV  r4, #CONSOLE
.word:  MOV  r1, [r5]+
        MOV  r2, #8
.digit: ROR  r1, #28            ; rotate left 4: the next digit to bits 3-0
        MOV  r3, r1
        AND  r3, #15
        MOV  r3, byte [hexdigits + r3]
        MOV  byte [r4], r3
        DBNZ r2, .digit
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
pad:    .space 128              ; the padded last block(s)
msg1000:
        .space 1000
