; String and memory routines.
;
;   strlen   r1 = s                      -> r1 = length
;   strcpy   r1 = dst, r2 = src          -> r1 = dst
;   strcmp   r1 = a, r2 = b              -> r1 < 0, 0, > 0 (difference of the first
;                                           differing bytes, compared unsigned)
;   memcpy   r1 = dst, r2 = src, r3 = n  -> r1 = dst (copies forward; use memmove
;                                           when the areas overlap)
;   memmove  r1 = dst, r2 = src, r3 = n  -> r1 = dst (any overlap)
;   memset   r1 = dst, r2 = byte, r3 = n -> r1 = dst
;
; memcpy and memset move whole words when the addresses allow it.
; All of them clobber r1-r7 at most.

        .align 2

; LEA doesn't touch the flags, so it can advance a pointer between a load and
; the branch that tests the loaded byte.
strlen: MOV  r2, r1
.loop:  LDB  r3, [r2]
        LEA  r2, [r2 + 1]
        BNE  .loop
        NOT  r1                 ; r2 is one past the NUL:
        ADD  r1, r2             ; length = r2 - r1 - 1 = r2 + ~r1
        RET

strcpy: MOV  r3, r1
.loop:  LDB  r4, [r2]
        STB  r4, [r3]           ; stores leave the flags alone too
        LEA  r2, [r2 + 1]
        LEA  r3, [r3 + 1]
        BNE  .loop
        RET

strcmp: LDB  r3, [r1]
        LDB  r4, [r2]
        SUB  r3, r4             ; bytes are zero-extended: no overflow possible
        BNE  .done
        TST  r4, r4             ; equal so far; stop at the shared NUL
        BEQ  .done
        INC  r1
        INC  r2
        BRA  strcmp
.done:  MOV  r1, r3
        RET

memcpy: MOV  r7, r1             ; return value
        MOV  r4, r1
        XOR  r4, r2
        SHR  r0, r4             ; C = dst and src differ in bit 0: no word can
        BCS  .bytes             ; be aligned for both, copy bytes
        SHR  r0, r1             ; C = both odd
        BCC  .even
        TST  r3, r3
        BEQ  .done
        LDB  r4, [r2]           ; one byte to reach even addresses
        STB  r4, [r1]
        INC  r1
        INC  r2
        DEC  r3
.even:  SHR  r5, r3             ; r5 = words
        SHR  r6, r5
        SHR  r6                 ; r6 = groups of four words
        BEQ  .rest
.quad:  LD   r4, [r2]
        ST   r4, [r1]
        LD   r4, [r2 + 2]
        ST   r4, [r1 + 2]
        LD   r4, [r2 + 4]
        ST   r4, [r1 + 4]
        LD   r4, [r2 + 6]
        ST   r4, [r1 + 6]
        ADDI r1, 8
        ADDI r2, 8
        DEC  r6
        BNE  .quad
.rest:  AND  r5, #3
        BEQ  .tail
.words: LD   r4, [r2]
        ST   r4, [r1]
        ADDI r1, 2
        ADDI r2, 2
        DEC  r5
        BNE  .words
.tail:  AND  r3, #1             ; an odd byte left over?
.bytes: TST  r3, r3
        BEQ  .done
.bloop: LDB  r4, [r2]
        STB  r4, [r1]
        INC  r1
        INC  r2
        DEC  r3
        BNE  .bloop
.done:  MOV  r1, r7
        RET

; Copy backwards only when dst lies inside (src, src + n).
memmove:
        MOV  r4, r1
        SUB  r4, r2             ; dst - src
        BLS  memcpy             ; dst <= src (unsigned): forward is safe
        CMP  r4, r3
        BHS  memcpy             ; dst >= src + n: no overlap
        MOV  r7, r1
        TST  r3, r3
        BEQ  .done
        ADD  r1, r3
        ADD  r2, r3
.loop:  DEC  r1
        DEC  r2
        LDB  r4, [r2]
        STB  r4, [r1]
        DEC  r3
        BNE  .loop
.done:  MOV  r1, r7
        RET

memset: MOV  r7, r1
        ZXT  r2                 ; the fill byte in both halves of a word
        SWAB r4, r2
        OR   r2, r4
        SHR  r0, r1             ; C = dst is odd
        BCC  .even
        TST  r3, r3
        BEQ  .done
        STB  r2, [r1]           ; one byte to reach an even address
        INC  r1
        DEC  r3
.even:  SHR  r5, r3             ; r5 = words
        SHR  r6, r5
        SHR  r6                 ; r6 = groups of four words
        BEQ  .rest
.quad:  ST   r2, [r1]
        ST   r2, [r1 + 2]
        ST   r2, [r1 + 4]
        ST   r2, [r1 + 6]
        ADDI r1, 8
        DEC  r6
        BNE  .quad
.rest:  AND  r5, #3
        BEQ  .tail
.words: ST   r2, [r1]
        ADDI r1, 2
        DEC  r5
        BNE  .words
.tail:  SHR  r0, r3             ; C = an odd byte left over
        BCC  .done
        STB  r2, [r1]
.done:  MOV  r1, r7
        RET
