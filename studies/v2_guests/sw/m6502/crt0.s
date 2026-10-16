; C start-up for the 6502 guest (cc65): the 6502's stack, cc65's C stack
; from 0xE000 down, the library's constructors, main, then JAM, which halts.
        .export   _exit
        .export   __STARTUP__ : absolute = 1
        .import   _main, initlib
        .importzp sp

        .segment  "STARTUP"
start:  ldx     #$FF
        txs
        cld
        lda     #$00
        sta     sp
        lda     #$E0
        sta     sp+1
        jsr     initlib
        jsr     _main
_exit:  .byte   $02

        .segment  "VECTORS"
        .word   start, start, start
