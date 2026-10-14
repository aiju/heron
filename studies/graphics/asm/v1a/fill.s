; fill_rows(job): the fill kernel, in draft 1a. src/gfx.c has the C
; version and src/gfx.h the job: h rows of words from p, pitch bytes
; apart; in each, the first word under lmask, n whole words, then one
; under rmask (none if rmask is 0).
;
; FillJob: p 0, pitch 4, h 8, lmask 12, n 16, rmask 20, pat 24, rop 28
;
; COPY stores the whole words eight at a time, with the short offsets
; and one ADDI; the other rops read, change and write a word at a time.

        .global _fill_rows
        .section .text._fill_rows
_fill_rows:
        SAVE r8-r14
        LD   r2, [r1]           ; r2: the row
        LD   r4, [r1 + 8]       ; r4: rows left
        BLE  .done
        LD   r8, [r1 + 24]      ; r8: the pattern
        LD   r5, [r1 + 12]      ; r5: lmask
        LD   r7, [r1 + 20]      ; r7: rmask
        LD   r6, [r1 + 16]      ; r6: whole words
        LD   r12, [r1 + 4]      ; r12: the pitch
        LD   r3, [r1 + 28]      ; the rop
        BNE  .rmw
; COPY: the edges as (v & ~m) | (pat & m)
        MOV  r9, r8
        AND  r9, r5             ; r9: pat & lmask
        MOV  r10, r8
        AND  r10, r7            ; r10: pat & rmask
        MOV  r11, r6
        LSR  r11, #3            ; r11: groups of 8 words
        AND  r6, #7             ; r6: and single words
.crow:  LD   r3, [r2]
        BIC  r3, r5
        OR   r3, r9
        ST   r3, [r2]
        LEA  r13, [r2 + 4]
        MOV  r14, r11
        BEQ  .crem
.c8:    ST   r8, [r13]
        ST   r8, [r13 + 4]
        ST   r8, [r13 + 8]
        ST   r8, [r13 + 12]
        ST   r8, [r13 + 16]
        ST   r8, [r13 + 20]
        ST   r8, [r13 + 24]
        ST   r8, [r13 + 28]
        ADDI r13, 32
        DEC  r14
        BNE  .c8
.crem:  MOV  r14, r6
        BEQ  .clast
.c1:    ST   r8, [r13]
        ADDI r13, 4
        DEC  r14
        BNE  .c1
.clast: TST  r7, r7
        BEQ  .cnext
        LD   r3, [r13]
        BIC  r3, r7
        OR   r3, r10
        ST   r3, [r13]
.cnext: ADD  r2, r12
        DEC  r4
        BNE  .crow
.done:  RESTORE r8-r14
        RET

; XOR, OR and AND: the edges with r9 and r10, the whole words with the
; pattern; AND clears (v & ~(m & ~pat)) so that it can use BIC at the edges
.rmw:   CMPI r3, 2
        BEQ  .or
        BHI  .and
        MOV  r9, r8
        AND  r9, r5
        MOV  r10, r8
        AND  r10, r7
.xrow:  LD   r3, [r2]
        XOR  r3, r9
        ST   r3, [r2]
        LEA  r13, [r2 + 4]
        MOV  r14, r6
        BEQ  .xlast
.x1:    LD   r3, [r13]
        XOR  r3, r8
        ST   r3, [r13]
        ADDI r13, 4
        DEC  r14
        BNE  .x1
.xlast: TST  r7, r7
        BEQ  .xnext
        LD   r3, [r13]
        XOR  r3, r10
        ST   r3, [r13]
.xnext: ADD  r2, r12
        DEC  r4
        BNE  .xrow
        BRA  .done

.or:    MOV  r9, r8
        AND  r9, r5
        MOV  r10, r8
        AND  r10, r7
.orow:  LD   r3, [r2]
        OR   r3, r9
        ST   r3, [r2]
        LEA  r13, [r2 + 4]
        MOV  r14, r6
        BEQ  .olast
.o1:    LD   r3, [r13]
        OR   r3, r8
        ST   r3, [r13]
        ADDI r13, 4
        DEC  r14
        BNE  .o1
.olast: TST  r7, r7
        BEQ  .onext
        LD   r3, [r13]
        OR   r3, r10
        ST   r3, [r13]
.onext: ADD  r2, r12
        DEC  r4
        BNE  .orow
        BRA  .done

.and:   MOV  r9, r5
        BIC  r9, r8             ; r9: lmask & ~pat, the bits to clear
        MOV  r10, r7
        BIC  r10, r8
.arow:  LD   r3, [r2]
        BIC  r3, r9
        ST   r3, [r2]
        LEA  r13, [r2 + 4]
        MOV  r14, r6
        BEQ  .alast
.a1:    LD   r3, [r13]
        AND  r3, r8
        ST   r3, [r13]
        ADDI r13, 4
        DEC  r14
        BNE  .a1
.alast: TST  r7, r7
        BEQ  .anext
        LD   r3, [r13]
        BIC  r3, r10
        ST   r3, [r13]
.anext: ADD  r2, r12
        DEC  r4
        BNE  .arow
        BRA  .done
