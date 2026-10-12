; String and memory routines (draft 1b).
;
;   strlen   r1 = s                        -> r1 = length                 clobbers r1-r3
;   strcpy   r1 = dst, r2 = src            -> r1 = dst                    clobbers r2-r4
;   strcmp   r1 = a, r2 = b                -> r1 < 0, 0 or > 0: the difference of the
;                                             first differing bytes, compared unsigned
;                                                                         clobbers r1-r4
;   memcpy   r1 = dst, r2 = src, r3 = n    -> r1 = dst                    clobbers r2-r5, r7
;            (copies forward: use memmove when the areas overlap)
;   memmove  r1 = dst, r2 = src, r3 = n    -> r1 = dst, any overlap       clobbers r2-r5, r7
;   memset   r1 = dst, r2 = byte, r3 = n   -> r1 = dst                    clobbers r2-r5, r7, HI
;
; memcpy and memset move whole words, 16 bytes per loop, when the addresses
; allow it (dst and src equally aligned for memcpy); memmove copies bytes
; when it has to go backwards. Needs no other library file.

        .align 2

strlen: MOV  r2, r1
.loop:  MOV  r3, byte [r2]+     ; Z at the NUL
        BNE  .loop
        SUB  r2, r1             ; r2 = length + 1 (it is one past the NUL)
        DEC  r1, r2
        RET

strcpy: MOV  r3, r1             ; r1 is kept as the result
.loop:  MOV  r4, byte [r2]+
        ST   r4, byte [r3]+     ; stores leave the flags alone: Z is from the load
        BNE  .loop
        RET

strcmp: MOV  r3, byte [r1]+
        BEQ  .end               ; end of a: the result is 0 - b's byte
        SUB  r3, byte [r2]+     ; bytes are 0-255: no overflow
        BEQ  strcmp
        MOV  r1, r3
        RET
.end:   MOV  r4, byte [r2]
        NEG  r1, r4
        RET

memcpy: MOV  r7, r1             ; the result
        MOV  r4, r1
        XOR  r4, r2
        AND  r4, #3
        BNE  .bytes             ; dst and src can't both be word-aligned
        NEG  r4, r1
        AND  r4, #3             ; r4 = bytes before dst reaches a word boundary
        BEQ  .words
        CMP  r4, r3
        BHS  .bytes             ; the copy ends before that: bytes only
        SUB  r3, r4
.head:  MOV  r5, byte [r2]+
        ST   r5, byte [r1]+
        DEC  r4
        BNE  .head
.words: MOV  r5, r3
        LSR  r5, #4             ; r5 = blocks of 16 bytes
        BEQ  .rest
.block: MOV  r4, [r2]+
        ST   r4, [r1]+
        MOV  r4, [r2]+
        ST   r4, [r1]+
        MOV  r4, [r2]+
        ST   r4, [r1]+
        MOV  r4, [r2]+
        ST   r4, [r1]+
        DEC  r5
        BNE  .block
.rest:  MOV  r5, r3
        LSR  r5, #2
        AND  r5, #3             ; r5 = words left (0-3)
        BEQ  .tail
.word:  MOV  r4, [r2]+
        ST   r4, [r1]+
        DEC  r5
        BNE  .word
.tail:  AND  r3, #3             ; bytes left (0-3)
.bytes: TST  r3, r3
        BEQ  .done
.bloop: MOV  r4, byte [r2]+
        ST   r4, byte [r1]+
        DEC  r3
        BNE  .bloop
.done:  MOV  r1, r7
        RET

; Forward copying is safe unless dst lies inside (src, src + n). One unsigned
; compare checks both ends: dst - src wraps round to a huge number when dst is
; below src. Going backwards, the count doubles as the index, so the pointers
; never move (there is no byte auto-decrement mode).
memmove:
        MOV  r4, r1
        SUB  r4, r2
        CMP  r4, r3
        BHS  memcpy             ; dst - src >= n: forwards (n = 0 also goes here)
.back:  MOV  r4, byte [r2 + r3 - 1]
        ST   r4, byte [r1 + r3 - 1]
        DEC  r3
        BNE  .back
        RET

memset: MOV  r7, r1             ; the result
        ZXB  r2
        MOV  r4, #0x01010101
        MULU r2, r4             ; the byte in all four lanes of a word
        NEG  r4, r1
        AND  r4, #3             ; r4 = bytes before dst reaches a word boundary
        BEQ  .words
        CMP  r4, r3
        BHS  .bytes             ; the fill ends before that: bytes only
        SUB  r3, r4
.head:  ST   r2, byte [r1]+
        DEC  r4
        BNE  .head
.words: MOV  r5, r3
        LSR  r5, #4             ; r5 = blocks of 16 bytes
        BEQ  .rest
.block: ST   r2, [r1]+
        ST   r2, [r1]+
        ST   r2, [r1]+
        ST   r2, [r1]+
        DEC  r5
        BNE  .block
.rest:  MOV  r5, r3
        LSR  r5, #2
        AND  r5, #3             ; r5 = words left (0-3)
        BEQ  .tail
.word:  ST   r2, [r1]+
        DEC  r5
        BNE  .word
.tail:  AND  r3, #3             ; bytes left (0-3)
.bytes: TST  r3, r3
        BEQ  .done
.bloop: ST   r2, byte [r1]+
        DEC  r3
        BNE  .bloop
.done:  MOV  r1, r7
        RET
