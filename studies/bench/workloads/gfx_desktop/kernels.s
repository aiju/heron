; gfx_desktop's kernels: fills, XOR fills and copies of rectangles on the
; 4-bit framebuffer, the edge masks they share with the text, and the
; screen's checksum. They follow Fen's window system's kernels
; (studies/fen/srv/wsys/kernels.s) and Heron Mini's graphics library
; (studies/mini_gfx/gfx/asm): words at a time, the first and last word of
; a row under a mask, d ^ ((d ^ v) & m).
;
; The framebuffer is 640 x 480, 320 bytes a row, Heron Mini's M0 layout:
; pixel p of a word is bits 4p to 4p + 3, so a row's pixels run from a
; word's low nibble to its high one, and from one word to the next. A
; rectangle is x0, y0, x1, y1 with x1 and y1 just outside it. A row's
; address is y * 320 as y * 256 + y * 64: two shifts and an add are a few
; cycles, a multiply many. The C calling convention throughout: arguments
; in r1-r4 then on the stack, r0-r7 the caller's to save, r8-r14 the
; callee's.

PITCH = 320                     ; bytes a row

        .global fb, clip_x0, clip_y0, clip_x1, clip_y1, fill_pat
        .global fill_rect, xor_rect, copy_rect, clip_mask, checksum
        .global left9, right9
        .far fb

        .text

; clip_span: the rectangle in r1-r4 clipped to `clip`, as the fills want
; it: r3 its rows (0 if nothing is left, and then nothing else is set),
; r2 the address of its first row's first word, r1 its first row, r4 the
; whole words between the first word and the last, r5 the first word's
; mask, r6 the last's (0 when the first word is the last, r5 then the
; mask of both). Uses r0; returns through r7.
clip_span:
        MOV  r0, [clip_x0]      ; x0, y0 up to the clip's; x1, y1 down
        CMP  r1, r0
        BGE  .1
        MOV  r1, r0
.1:     MOV  r0, [clip_y0]
        CMP  r2, r0
        BGE  .2
        MOV  r2, r0
.2:     MOV  r0, [clip_x1]
        CMP  r3, r0
        BLE  .3
        MOV  r3, r0
.3:     MOV  r0, [clip_y1]
        CMP  r4, r0
        BLE  .4
        MOV  r4, r0
.4:     SUB  r4, r2             ; r4: rows
        BLE  .none
        CMP  r3, r1
        BLE  .none
        DEC  r3                 ; r3: the last pixel
        MOV  r5, r1
        AND  r5, #7
        MOV  r5, [left9 + r5*4] ; r5: from x0's pixel to the word's end
        MOV  r6, r3
        AND  r6, #7
        MOV  r6, [right9 + 4 + r6*4]    ; r6: to the last pixel
        ASR  r1, #3             ; r1, r3: the first and last words
        ASR  r3, #3
        SUB  r3, r1             ; words after the first
        BNE  .wide
        AND  r5, r6             ; one word: both masks in r5
        CLR  r6
        INC  r3                 ; so r4 = 0 below
.wide:  DEC  r3                 ; r3: the middle words
        LSL  r1, #2             ; r1: the first word's address,
        ADD  r1, #fb            ; fb + y0 x 320 + 4 x its word
        MOV  r0, r2
        LSL  r0, #8
        ADD  r1, r0
        MOV  r0, r2
        LSL  r0, #6
        ADD  r1, r0
        MOV  r0, r1             ; into place: r1 and r2 swapped,
        MOV  r1, r2             ; and r3 and r4
        MOV  r2, r0
        MOV  r0, r3
        MOV  r3, r4
        MOV  r4, r0
        RET
.none:  CLR  r3
        RET

; fill_rect(x0, y0, x1, y1): the rectangle, clipped to `clip`, filled with
; fill_pat: its first word on even rows, its second on odd ones (a
; two-row pattern fixed to the screen, as a desktop's background is; a
; solid colour has both the same). The whole words go eight a loop.
fill_rect:
        SAVE r7-r14
        BSR  clip_span
        TST  r3, r3
        BEQ  .done
        MOV  r8, [fill_pat]     ; r8: this row's pattern, r9 the next's
        MOV  r9, [fill_pat + 4]
        TST  r1, #1
        BEQ  .even
        MOV  r0, r8
        MOV  r8, r9
        MOV  r9, r0
.even:  MOV  r11, r4
        LSR  r11, #3            ; r11: middle words in eights
        AND  r4, #7             ; r4: and the rest
        MOV  r12, #PITCH
.row:   MOV  r10, r2
        MOV  r0, [r10]          ; the first word under r5
        MOV  r1, r0
        XOR  r1, r8
        AND  r1, r5
        XOR  r0, r1
        MOV  [r10]+, r0
        TST  r6, r6
        BEQ  .next              ; one word: done
        MOVS r13, r11
        BEQ  .rest
.f8:    MOV  [r10]+, r8
        MOV  [r10]+, r8
        MOV  [r10]+, r8
        MOV  [r10]+, r8
        MOV  [r10]+, r8
        MOV  [r10]+, r8
        MOV  [r10]+, r8
        MOV  [r10]+, r8
        DBNZ r13, .f8
.rest:  MOVS r13, r4
        BEQ  .last
.f1:    MOV  [r10]+, r8
        DBNZ r13, .f1
.last:  MOV  r0, [r10]          ; the last word under r6
        MOV  r1, r0
        XOR  r1, r8
        AND  r1, r6
        XOR  r0, r1
        MOV  [r10], r0
.next:  MOV  r0, r8             ; the other row's pattern
        MOV  r8, r9
        MOV  r9, r0
        ADD  r2, r12
        DEC  r3
        BNE  .row
.done:  RESTORE r7-r14
        RET

; xor_rect(x0, y0, x1, y1): the rectangle, clipped to `clip`, inverted:
; every pixel's colour XORed with 15, as a selection is shown.
xor_rect:
        SAVE r7-r14
        BSR  clip_span
        TST  r3, r3
        BEQ  .done
        MOV  r12, #PITCH
.row:   MOV  r10, r2
        MOV  r0, [r10]
        XOR  r0, r5
        MOV  [r10]+, r0
        TST  r6, r6
        BEQ  .next
        MOVS r13, r4
        BEQ  .last
.mid:   MOV  r0, [r10]
        NOT  r0
        MOV  [r10]+, r0
        DBNZ r13, .mid
.last:  MOV  r0, [r10]
        XOR  r0, r6
        MOV  [r10], r0
.next:  ADD  r2, r12
        DEC  r3
        BNE  .row
.done:  RESTORE r7-r14
        RET

; copy_rect(dx, dy, sx, sy, w, h): the w x h pixels at (sx, sy) copied to
; (dx, dy), not clipped: both must be on the screen. They may overlap: the
; rows go bottom up when the copy moves down, and right to left when it
; moves right along the same rows, so no pixel is read after it's written.
;
; Destination word j of a row takes its pixels from the source row from
; pixel 8j - (dx - sx): with rs = 4 x ((sx - dx) mod 8), the source words
; lo and hi = lo + 1 give (lo >> rs) | (hi << 32 - rs), and with rs = 0
; just lo. The first and last words go under the edge masks; the words
; read beyond the source's ends only feed bits the masks drop.
;
; Through the rows: r2 the destination row's first word (its last, right
; to left), r3 the source's word for it, r4 rows left, r5 and r6 the first
; and last word's masks, r8 rs, r9 32 - rs, r10 the middle words, r11 the
; step from row to row; r7 and r1 run along the row, r12 and r13 are the
; words in hand and r14 counts.
copy_rect:
        SAVE r7-r14
        MOVS r10, [sp + 32]     ; r10: w, r11: h, from the stack above
        BLE  .done              ; the eight saved registers
        MOVS r11, [sp + 36]
        BLE  .done
        ; the destination's words: r12 the first, r14 the last less it
        MOV  r12, r1
        ASR  r12, #3
        MOV  r14, r1
        ADD  r14, r10
        DEC  r14                ; the last pixel
        MOV  r6, r14
        AND  r6, #7
        MOV  r6, [right9 + 4 + r6*4]    ; r6: the last word's mask
        ASR  r14, #3
        SUB  r14, r12
        ; the shift, from the source pixel that lands on the first
        ; word's first pixel: sx - (dx mod 8)
        MOV  r5, r1
        AND  r5, #7
        MOV  r13, r3
        SUB  r13, r5
        MOV  r8, r13
        AND  r8, #7
        LSL  r8, #2             ; r8: rs
        MOV  r9, #32
        SUB  r9, r8             ; r9: 32 - rs
        ASR  r13, #3            ; r13: the source's word for the first
        MOV  r5, [left9 + r5*4] ; r5: the first word's mask
        ; right to left only if dy = sy, dx > sx and two words or more
        CLR  r7                 ; r7: 1 for right to left
        TST  r14, r14
        BNE  .two
        AND  r5, r6             ; one word: both masks in r5
        CLR  r6
        BRA  .order
.two:   CMP  r2, r4
        BNE  .order
        CMP  r1, r3
        BLE  .order
        MOV  r7, #1
        ; the rows: top down from dy and sy, or bottom up from their last
.order: MOV  r10, r14
        DEC  r10                ; r10: the middle words
        MOV  r1, #PITCH         ; r1: the step
        CMP  r2, r4
        BLE  .addr
        ADD  r2, r11
        DEC  r2
        ADD  r4, r11
        DEC  r4
        NEG  r1
.addr:  MOV  r0, r2             ; r2: the destination row's first word
        LSL  r0, #8
        LSL  r2, #6
        ADD  r2, r0
        ADD  r2, #fb
        LSL  r12, #2
        ADD  r2, r12
        MOV  r0, r4             ; r4: the source's word for it
        LSL  r0, #8
        LSL  r4, #6
        ADD  r4, r0
        ADD  r4, #fb
        LSL  r13, #2
        ADD  r4, r13
        MOV  r3, r4
        MOV  r4, r11            ; r4: rows
        MOV  r11, r1            ; r11: the step
        TST  r7, r7
        BNE  .back
        TST  r8, r8
        BEQ  .fal

; left to right, shifted: the first word from lo and hi, then a word for
; each word read
.fsh:   MOV  r7, r2
        MOV  r1, r3
        MOV  r12, [r1]+         ; lo
        MOV  r13, [r1]+         ; hi
        MOV  r0, r12
        LSR  r0, r8
        MOV  r12, r13
        LSL  r13, r9
        OR   r0, r13
        MOV  r13, [r7]          ; the first word under r5
        XOR  r0, r13
        AND  r0, r5
        XOR  r13, r0
        MOV  [r7]+, r13
        TST  r6, r6
        BEQ  .fsnext
        MOVS r14, r10
        BEQ  .fslast
.fsmid: MOV  r13, [r1]+
        MOV  r0, r12
        LSR  r0, r8
        MOV  r12, r13
        LSL  r13, r9
        OR   r0, r13
        MOV  [r7]+, r0
        DBNZ r14, .fsmid
.fslast:
        MOV  r13, [r1]          ; the last word under r6
        MOV  r0, r12
        LSR  r0, r8
        LSL  r13, r9
        OR   r0, r13
        MOV  r13, [r7]
        XOR  r0, r13
        AND  r0, r6
        XOR  r13, r0
        MOV  [r7], r13
.fsnext:
        ADD  r2, r11
        ADD  r3, r11
        DEC  r4
        BNE  .fsh
        BRA  .done

; left to right, not shifted: the middle words four a loop
.fal:   MOV  r12, r10
        LSR  r12, #2            ; r12: fours
        AND  r10, #3            ; r10: the rest
.farow: MOV  r7, r2
        MOV  r1, r3
        MOV  r0, [r1]+          ; the first word under r5
        MOV  r13, [r7]
        XOR  r0, r13
        AND  r0, r5
        XOR  r13, r0
        MOV  [r7]+, r13
        TST  r6, r6
        BEQ  .fanext
        MOVS r14, r12
        BEQ  .farest
.fa4:   MOV  r0, [r1]+
        MOV  [r7]+, r0
        MOV  r0, [r1]+
        MOV  [r7]+, r0
        MOV  r0, [r1]+
        MOV  [r7]+, r0
        MOV  r0, [r1]+
        MOV  [r7]+, r0
        DBNZ r14, .fa4
.farest:
        MOVS r14, r10
        BEQ  .falast
.fa1:   MOV  r0, [r1]+
        MOV  [r7]+, r0
        DBNZ r14, .fa1
.falast:
        MOV  r0, [r1]           ; the last word under r6
        MOV  r13, [r7]
        XOR  r0, r13
        AND  r0, r6
        XOR  r13, r0
        MOV  [r7], r13
.fanext:
        ADD  r2, r11
        ADD  r3, r11
        DEC  r4
        BNE  .farow
.done:  RESTORE r7-r14
        RET

; right to left (two words or more): from the last word, r2 and r3 moved
; to it; shifted, r3 to its hi
.back:  MOV  r0, r14
        LSL  r0, #2
        ADD  r2, r0
        ADD  r3, r0
        TST  r8, r8
        BEQ  .bal
        ADD  r3, #4
.bsh:   MOV  r7, r2
        MOV  r1, r3
        MOV  r13, [r1]          ; hi
        MOV  r12, -[r1]         ; lo
        MOV  r0, r12
        LSR  r0, r8
        LSL  r13, r9
        OR   r0, r13
        MOV  r13, [r7]          ; the last word under r6
        XOR  r0, r13
        AND  r0, r6
        XOR  r13, r0
        MOV  [r7], r13
        MOVS r14, r10
        BEQ  .bsfirst
.bsmid: MOV  r13, r12           ; this word's hi is the last one's lo
        MOV  r12, -[r1]
        MOV  r0, r12
        LSR  r0, r8
        LSL  r13, r9
        OR   r0, r13
        MOV  -[r7], r0
        DBNZ r14, .bsmid
.bsfirst:
        MOV  r13, r12
        MOV  r12, -[r1]
        MOV  r0, r12
        LSR  r0, r8
        LSL  r13, r9
        OR   r0, r13
        MOV  r13, -[r7]         ; the first word under r5
        XOR  r0, r13
        AND  r0, r5
        XOR  r13, r0
        MOV  [r7], r13
        ADD  r2, r11
        ADD  r3, r11
        DEC  r4
        BNE  .bsh
        BRA  .done

; right to left, not shifted
.bal:   MOV  r7, r2
        MOV  r1, r3
        MOV  r0, [r1]           ; the last word under r6
        MOV  r13, [r7]
        XOR  r0, r13
        AND  r0, r6
        XOR  r13, r0
        MOV  [r7], r13
        MOVS r14, r10
        BEQ  .bafirst
.bamid: MOV  r0, -[r1]
        MOV  -[r7], r0
        DBNZ r14, .bamid
.bafirst:
        MOV  r0, -[r1]          ; the first word under r5
        MOV  r13, -[r7]
        XOR  r0, r13
        AND  r0, r5
        XOR  r13, r0
        MOV  [r7], r13
        ADD  r2, r11
        ADD  r3, r11
        DEC  r4
        BNE  .bal
        BRA  .done

; clip_mask(w): r1 = the mask of word w's pixels inside the clip's
; columns, from the tables of left and right edges. Uses r0 and r2.
clip_mask:
        LSL  r1, #3             ; the word's first pixel
        MOV  r0, [clip_x0]
        SUB  r0, r1             ; the clip's columns from it: r0 to r2
        MOV  r2, [clip_x1]
        SUB  r2, r1
        TST  r0, r0             ; both into 0...8
        BPL  .1
        CLR  r0
.1:     CMP  r0, #8
        BLE  .2
        MOV  r0, #8
.2:     TST  r2, r2
        BPL  .3
        CLR  r2
.3:     CMP  r2, #8
        BLE  .4
        MOV  r2, #8
.4:     MOV  r1, [left9 + r0*4]
        AND  r1, [right9 + r2*4]
        RET

; checksum(): r1 = the sum of the screen's words, r2 = the sum of those
; sums, a word after another (Fletcher's second sum), four words a loop.
checksum:
        MOV  r3, #fb
        MOV  r4, #SH
        CLR  r1
        CLR  r2
.row:   MOV  r5, #SW / 32
        MOV  r6, r3
.w4:    ADD  r1, [r6]+
        ADD  r2, r1
        ADD  r1, [r6]+
        ADD  r2, r1
        ADD  r1, [r6]+
        ADD  r2, r1
        ADD  r1, [r6]+
        ADD  r2, r1
        DBNZ r5, .w4
        ADD  r3, #PITCH
        DEC  r4
        BNE  .row
        RET

        .data
        .align 4
; left9[i]: a word's pixels from i on; right9[i]: its pixels before i
left9:  .word 0xFFFFFFFF, 0xFFFFFFF0, 0xFFFFFF00, 0xFFFFF000, 0xFFFF0000
        .word 0xFFF00000, 0xFF000000, 0xF0000000, 0
right9: .word 0, 0x0000000F, 0x000000FF, 0x00000FFF, 0x0000FFFF
        .word 0x000FFFFF, 0x00FFFFFF, 0x0FFFFFFF, 0xFFFFFFFF

; the clip rectangle every drawing routine keeps to, and the fills' pattern
clip_x0: .word 0
clip_y0: .word 0
clip_x1: .word 0
clip_y1: .word 0
fill_pat: .word 0, 0

; the framebuffer, and a few words after it that the kernels may read
; (and write back unchanged) past the last row's end
        .section .farbss.fb
        .align 4
fb:     .space PITCH * 480 + 16
