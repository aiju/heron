; debug: Heron Mini's debug button at chip level (board.py's U_DBGB, RFC
; 0041). The program counts in a loop with interrupts off; the button,
; pressed while it does, takes the debug entry all the same: vector 0x1C,
; the flags word and the PC pushed as an interrupt's are. The handler
; prints "debug", whether the count had started and the saved flags' I
; (off), then HALTs. The console is the suite's I/O page.

        .org 0x00
        JMP  start
        .org 0x04
        JMP  fatal
        .org 0x08
        JMP  fatal
        .org 0x0C
        JMP  fatal
        .org 0x10
        JMP  fatal
        .org 0x14
        JMP  fatal
        .org 0x18
        JMP  fatal
        .org 0x1C
        JMP  dbg

CONSOLE  = 0xFFFFFF00

start:  MOV  sp, #0x100000
        DI
        CLR  r1
.loop:  INC  r1
        BRA  .loop

dbg:    MOV  r11, #CONSOLE
        LEA  r2, [s_dbg]
.s:     MOVS r3, byte [r2]+
        BEQ  .sd
        MOV  byte [r11], r3
        BRA  .s
.sd:    CMP  r1, #0             ; counting?
        MOV  r3, #'y'
        BNE  .c
        MOV  r3, #'n'
.c:     MOV  byte [r11], r3
        MOV  r3, [sp]           ; the flags word: I is bit 4
        LSR  r3, #4
        AND  r3, #1
        ADD  r3, #'0'
        MOV  byte [r11], r3
        MOV  r3, #10
        MOV  byte [r11], r3
        HALT

fatal:  DI
        HALT

s_dbg:  .ascii "debug "
        .byte 0
