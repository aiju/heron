; The what-if block instructions (whatif.py) from C, for the wif variant:
; each a call's arguments in its registers, any count (256 at a time).
;
;   void wif_fillx(unsigned *d, unsigned v, int n)             FD 04
;   void wif_expandt(unsigned *d, const unsigned char *s, int n,
;                    const unsigned *table, unsigned fg)       FD 05
;   void wif_expand2(unsigned *d, const unsigned char *s, int n,
;                    const unsigned *t0, const unsigned *t1,
;                    unsigned fg_xor_bg, unsigned bg)          FD 06
;   void wif_expand1(unsigned *d, const unsigned *s, int n,
;                    unsigned fg_xor_bg, unsigned bg)          FD 07
;   void wif_expand8(unsigned *d, const unsigned char *s, int n,
;                    const unsigned *table2, unsigned fg_xor_bg, unsigned bg)  FD 08
;   unsigned wif_blitn(unsigned *d, const unsigned *s, int n, int bits,
;                      unsigned lo, unsigned mask)             FD 2n
;   void wif_patch(const ExpandJob *j)          expand.s's aligning, set up
;   const unsigned char *wif_align(const unsigned *s, int bytes)   and done

        .global _wif_fillx, _wif_expandt, _wif_expand2, _wif_expand1, _wif_expand8
        .global _wif_blitn, _wif_patch, _wif_align

        .section .text._wif_fillx
_wif_fillx:
        MOV  r4, r3
.l:     MOV  r3, r4
        CMP  r3, #256
        BLS  .go
        MOV  r3, #256
.go:    TST  r3, r3
        BEQ  .done
        .half 0x04FD            ; FILLX
        SUB  r4, r3
        BNE  .l
.done:  RET

        .section .text._wif_expandt
_wif_expandt:
        MOV  r5, [sp]
        MOV  r0, r3
.l:     MOV  r3, r0
        CMP  r3, #256
        BLS  .go
        MOV  r3, #256
.go:    TST  r3, r3
        BEQ  .done
        .half 0x05FD            ; EXPANDT
        SUB  r0, r3
        BNE  .l
.done:  RET

        .section .text._wif_expand2
_wif_expand2:
        SAVE r8
        MOV  r0, [sp + 4]       ; t1
        MOV  r5, [sp + 8]
        MOV  r6, [sp + 12]
        MOV  r8, r3
.l:     MOV  r3, r8
        CMP  r3, #256
        BLS  .go
        MOV  r3, #256
.go:    TST  r3, r3
        BEQ  .done
        .half 0x06FD            ; EXPAND2
        SUB  r8, r3
        BNE  .l
.done:  RESTORE r8
        RET

        .section .text._wif_expand1
_wif_expand1:
        MOV  r5, r4
        MOV  r6, [sp]
        MOV  r0, r3
.l:     MOV  r3, r0
        CMP  r3, #256
        BLS  .go
        MOV  r3, #256
.go:    TST  r3, r3
        BEQ  .done
        .half 0x07FD            ; EXPAND1
        SUB  r0, r3
        BNE  .l
.done:  RET

        .section .text._wif_expand8
_wif_expand8:
        MOV  r5, [sp]
        MOV  r6, [sp + 4]
        MOV  r0, r3
.l:     MOV  r3, r0
        CMP  r3, #256
        BLS  .go
        MOV  r3, #256
.go:    TST  r3, r3
        BEQ  .done
        .half 0x08FD            ; EXPAND8
        SUB  r0, r3
        BNE  .l
.done:  RET

; BLITN with n patched in (a jump between: the prefetch queue holds no old copy)
        .section .text._wif_blitn
_wif_blitn:
        SAVE r7-r8
        MOV  r8, r4
        AND  r8, #31
        LSL  r8, #8
        OR   r8, #0x20FD
        LEA  r0, [pc + .op]
        MOV  half [r0], r8
        MOV  r5, [sp + 8]       ; lo
        MOV  r8, [sp + 12]      ; the mask
        MOV  r4, r3
        BRA  .l
.l:     MOV  r3, r4
        CMP  r3, #256
        BLS  .go
        MOV  r3, #256
.go:    TST  r3, r3
        BEQ  .done
        MOV  r0, r8
.op:    .half 0x20FD            ; BLITN n
        SUB  r4, r3
        BNE  .l
.done:  MOV  r1, r5
        RESTORE r7-r8
        RET

        .section .text._wif_patch
_wif_patch:
        SAVE r7
        BSR  _xpand_patch
        RESTORE r7
        RET

        .section .text._wif_align
_wif_align:
        SAVE r7-r13
        MOV  r3, r2
        MOV  r2, r1
        BSR  _xpand_align
        MOV  r1, r3
        RESTORE r7-r13
        RET
