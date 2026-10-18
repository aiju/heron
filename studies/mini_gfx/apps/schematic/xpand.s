; The editor's kernels in draft 2 (xpand.c has the C and what they're for).
;
; sch_expand_asm(job): a 1-bit bitmap into 1- or 2-bit pixels. Each row in
; three steps: the source's bits lined up from bit soff (two words rotated
; by soff and merged, as gfx/asm/expand.s does: ROR #soff is patched into
; the loop, a jump after); the masks of the destination's words, by the
; format; then the pixels, by the mode, words with no pixels skipped
; (transparent and XOR) and the first and last under lmask and rmask.
;
; XJob: d 0, s 4, dpitch 8, spitch 12 (bytes), h 16, n 20, lmask 24,
; rmask 28, soff 32, fg 36, bg 40, mode 44 (0 transparent, 1 XOR,
; 2 opaque), fmt 48 (0 LIN1, 1 CHK1, 2 LIN2, 3 CHK2, 4 PL2), tab 52

        .global _sch_expand_asm, _sch_vline_asm
        .section .text._sch_expand_asm
_sch_expand_asm:
        SAVE r7-r14
        MOV  r14, r1            ; r14: the job
        MOV  r8, [r14]          ; r8: the destination row
        MOV  r9, [r14 + 4]      ; r9: the source row
        MOVS r12, [r14 + 16]    ; r12: rows left
        BLE  .done
; ROR #soff into the two rotations, and the mask of the top soff bits
        MOV  r2, [r14 + 32]
        MOV  r3, r2
        AND  r3, #1
        OR   r3, #0xCC
        MOV  r4, r2
        LSR  r4, #1
        LSL  r4, #8
        OR   r3, r4             ; ROR #soff, its register 0
        LEA  r4, [pc + .ra]
        MOV  r5, r3
        OR   r5, #0xB000        ; r11
        MOV  half [r4], r5
        LEA  r4, [pc + .rb]
        MOV  r5, r3
        OR   r5, #0xA000        ; r10
        MOV  half [r4], r5
        MOV  r3, #0
        TST  r2, r2
        BEQ  .z
        MOV  r3, #-1
        LSR  r3, r2             ; once a job: a shift by a register is fine
        NOT  r3
.z:     MOV  [_sch_xmask], r3
        BRA  .row               ; a jump: the prefetch queue holds no old copy

; the row's bits from bit 0: n + 1 words at 1 bit, half that at 2
.row:   MOV  r5, [r14 + 20]
        INC  r5                 ; r5: the row's words
        MOV  r3, r5
        MOV  r0, [r14 + 48]
        CMP  r0, #2
        BLO  .al
        INC  r3
        LSR  r3, #1             ; source words, at 2 bits
.al:    MOV  r0, [_sch_xmask]
        TST  r0, r0
        BNE  .rot
        MOV  r3, r9             ; soff 0: the source itself
        BRA  .masks
.rot:   LEA  r1, [_sch_xbuf]
        MOV  r2, r9
        MOV  r11, [r2]+
.ra:    ROR  r11, #1
.alp:   MOV  r10, [r2]+
.rb:    ROR  r10, #1
        MOV  r13, r11
        MERGE r13, r10, r0      ; s[k] >> soff | s[k + 1] << 32 - soff
        MOV  [r1]+, r13
        MOV  r11, r10
        DBNZ r3, .alp
        LEA  r3, [_sch_xbuf]

; the masks into _sch_mbuf (LIN1: the bits are the masks); r3 then points at them
.masks: MOV  r0, [r14 + 48]
        TST  r0, r0
        BEQ  .apply
        LEA  r4, [_sch_mbuf]
        MOV  r6, [r14 + 52]     ; r6: the table
        CMP  r0, #1
        BEQ  .chk1
        INC  r5
        LSR  r5, #1             ; pairs of words: a source word each
        CMP  r0, #3
        BEQ  .chk2
        BHI  .pl2

; LIN2: a byte's 8 pixels through the table, the next byte's 16 bits up;
; a source word of no pixels is two masks of none
.l2:    MOVS r1, [r3]+
        BNE  .l2w
        MOV  [r4]+, r1
        MOV  [r4]+, r1
        DEC  r5
        BNE  .l2
        BRA  .mdone
.l2w:   ZXB  r2, r1
        MOV  r2, [r6 + r2*4]
        MOV  r0, r1
        LSR  r0, #8
        ZXB  r0, r0
        MOV  r0, [r6 + r0*4]
        SWAP r0, r0
        OR   r2, r0
        MOV  [r4]+, r2
        SWAP r1, r1
        ZXB  r2, r1
        MOV  r2, [r6 + r2*4]
        LSR  r1, #8
        ZXB  r1, r1
        MOV  r1, [r6 + r1*4]
        SWAP r1, r1
        OR   r2, r1
        MOV  [r4]+, r2
        DEC  r5
        BNE  .l2
        BRA  .mdone

; CHK2: the first byte's pixels at 4b and 4b + 2, the second's a bit up
.chk2:  MOVS r1, [r3]+
        BNE  .c2w
        MOV  [r4]+, r1
        MOV  [r4]+, r1
        DEC  r5
        BNE  .chk2
        BRA  .mdone
.c2w:   ZXB  r2, r1
        MOV  r2, [r6 + r2*4]
        MOV  r0, r1
        LSR  r0, #8
        ZXB  r0, r0
        MOV  r0, [r6 + r0*4]
        ADD  r0, r0
        OR   r2, r0
        MOV  [r4]+, r2
        SWAP r1, r1
        ZXB  r2, r1
        MOV  r2, [r6 + r2*4]
        LSR  r1, #8
        ZXB  r1, r1
        MOV  r1, [r6 + r1*4]
        ADD  r1, r1
        OR   r2, r1
        MOV  [r4]+, r2
        DEC  r5
        BNE  .chk2
        BRA  .mdone

; PL2: a half and itself 16 bits up (the two planes)
.pl2:   MOV  r1, [r3]+
        ZXH  r2, r1
        MOV  r0, r2
        SWAP r0, r0
        OR   r2, r0
        MOV  [r4]+, r2
        SWAP r1, r1
        ZXH  r2, r1
        MOV  r0, r2
        SWAP r0, r0
        OR   r2, r0
        MOV  [r4]+, r2
        DBNZ r5, .pl2
        BRA  .mdone

; CHK1: byte j's pixels at 4b + j
.chk1:  MOVS r1, [r3]+
        BNE  .c1w
        MOV  [r4]+, r1
        DEC  r5
        BNE  .chk1
        BRA  .mdone
.c1w:   ZXB  r2, r1
        MOV  r2, [r6 + r2*4]
        LSR  r1, #8
        ZXB  r0, r1
        MOV  r0, [r6 + r0*4]
        ADD  r0, r0
        OR   r2, r0
        LSR  r1, #8
        ZXB  r0, r1
        MOV  r0, [r6 + r0*4]
        LSL  r0, #2
        OR   r2, r0
        LSR  r1, #8
        MOV  r0, [r6 + r1*4]
        LSL  r0, #3
        OR   r2, r0
        MOV  [r4]+, r2
        DEC  r5
        BNE  .chk1
.mdone: LEA  r3, [_sch_mbuf]

; the pixels: r3 the masks, r2 the destination, r5 the words after the first
.apply: MOV  r2, r8
        MOV  r5, [r14 + 20]
        MOV  r6, [r14 + 36]     ; r6: fg
        MOV  r10, [r14 + 24]    ; r10: lmask
        MOV  r11, [r14 + 28]    ; r11: rmask
        MOV  r0, [r14 + 44]
        TST  r0, r0
        BEQ  .trans
        CMP  r0, #1
        BEQ  .xor

; opaque: bg ^ ((fg ^ bg) & m), the edges merged
        MOV  r7, [r14 + 40]
        XOR  r6, r7
        MOV  r1, [r3]+
        AND  r1, r6
        XOR  r1, r7
        MOV  r0, [r2]
        XOR  r1, r0
        AND  r1, r10
        XOR  r0, r1
        MOV  [r2]+, r0
        TST  r5, r5
        BEQ  .next
        DEC  r5
        BEQ  .olast
.omid:  MOV  r1, [r3]+
        AND  r1, r6
        XOR  r1, r7
        MOV  [r2]+, r1
        DBNZ r5, .omid
.olast: MOV  r1, [r3]+
        AND  r1, r6
        XOR  r1, r7
        MOV  r0, [r2]
        XOR  r1, r0
        AND  r1, r11
        XOR  r0, r1
        MOV  [r2], r0
        BRA  .next

; XOR: d ^= fg & m
.xor:   MOV  r1, [r3]+
        AND  r1, r10
        AND  r1, r6
        MOV  r0, [r2]
        XOR  r0, r1
        MOV  [r2]+, r0
        TST  r5, r5
        BEQ  .next
        DEC  r5
        BEQ  .xlast
.xmid:  MOVS r1, [r3]+
        BEQ  .xskip
        AND  r1, r6
        MOV  r0, [r2]
        XOR  r0, r1
        MOV  [r2], r0
.xskip: ADD  r2, #4
        DBNZ r5, .xmid
.xlast: MOV  r1, [r3]+
        AND  r1, r11
        AND  r1, r6
        MOV  r0, [r2]
        XOR  r0, r1
        MOV  [r2], r0
        BRA  .next

; transparent: d ^= (d ^ fg) & m
.trans: MOV  r1, [r3]+
        AND  r1, r10
        MOV  r0, [r2]
        MOV  r13, r0
        XOR  r13, r6
        AND  r13, r1
        XOR  r0, r13
        MOV  [r2]+, r0
        TST  r5, r5
        BEQ  .next
        DEC  r5
        BEQ  .tlast
.tmid:  MOVS r1, [r3]+
        BEQ  .tskip
        MOV  r0, [r2]
        MOV  r13, r0
        XOR  r13, r6
        AND  r13, r1
        XOR  r0, r13
        MOV  [r2], r0
.tskip: ADD  r2, #4
        DBNZ r5, .tmid
.tlast: MOV  r1, [r3]+
        AND  r1, r11
        MOV  r0, [r2]
        MOV  r13, r0
        XOR  r13, r6
        AND  r13, r1
        XOR  r0, r13
        MOV  [r2], r0

.next:  ADD  r8, [r14 + 8]
        ADD  r9, [r14 + 12]
        DEC  r12
        BNE  .row
.done:  RESTORE r7-r14
        RET

; sch_vline_asm(p, pitch, n, m, v): n words from p, pitch bytes apart,
; each (w & ~m) | v, or with m 0, w ^ v; four rows a loop
        .section .text._sch_vline_asm
_sch_vline_asm:
        MOV  r5, [sp]           ; v, the fifth argument
        TST  r4, r4
        BEQ  .x
        MOV  r0, r3
        AND  r3, #3             ; r3: single rows
        LSR  r0, #2             ; r0: groups of four
        BEQ  .c1
.c4:    MOV  r6, [r1]
        BIC  r6, r4
        OR   r6, r5
        MOV  [r1], r6
        ADD  r1, r2
        MOV  r6, [r1]
        BIC  r6, r4
        OR   r6, r5
        MOV  [r1], r6
        ADD  r1, r2
        MOV  r6, [r1]
        BIC  r6, r4
        OR   r6, r5
        MOV  [r1], r6
        ADD  r1, r2
        MOV  r6, [r1]
        BIC  r6, r4
        OR   r6, r5
        MOV  [r1], r6
        ADD  r1, r2
        DEC  r0
        BNE  .c4
.c1:    TST  r3, r3
        BEQ  .cd
.c1l:   MOV  r6, [r1]
        BIC  r6, r4
        OR   r6, r5
        MOV  [r1], r6
        ADD  r1, r2
        DBNZ r3, .c1l
.cd:    RET
.x:     MOV  r0, r3
        AND  r3, #3
        LSR  r0, #2
        BEQ  .x1
.x4:    MOV  r6, [r1]
        XOR  r6, r5
        MOV  [r1], r6
        ADD  r1, r2
        MOV  r6, [r1]
        XOR  r6, r5
        MOV  [r1], r6
        ADD  r1, r2
        MOV  r6, [r1]
        XOR  r6, r5
        MOV  [r1], r6
        ADD  r1, r2
        MOV  r6, [r1]
        XOR  r6, r5
        MOV  [r1], r6
        ADD  r1, r2
        DEC  r0
        BNE  .x4
.x1:    TST  r3, r3
        BEQ  .xd
.x1l:   MOV  r6, [r1]
        XOR  r6, r5
        MOV  [r1], r6
        ADD  r1, r2
        DBNZ r3, .x1l
.xd:    RET

        .bss
        .align 4
        .global _sch_xmask
_sch_xmask:
        .space 4
