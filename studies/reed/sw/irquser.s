; irquser: the timer's interrupts taken from user mode (bank 1, the page
; map on, context 1), a loop whose result doesn't depend on when they
; come: its sum, the count of interrupts and the end's mark at LOG
W       = 0x80000000
TIMER   = 0xC0002000
LOG     = W + 0x10000
UCODE   = 0x5000
UDATA   = 0x9000

        .org W + 0x00
        JMP  boot
        .org W + 0x08
        JMP  bad
        .org W + 0x14
        JMP  bad
        .org W + 0x1C
        JMP  bad
        .org W + 0x20
        JMP  bad
        .org W + 0x54
        JMP  h_tick
        .org W + 0x58
        JMP  frame              ; level 7, the video's frame (at chip level: the model has no video)
        .org W + 0x104
        JMP  h_exit
        .org W + 0x200
; the video's frame: a write to its control register acknowledges it
frame:  PUSH r1
        MOV  r1, #0
        MOV  half [0xF0000400], r1
        POP  r1
        RTI

boot:   MOV  r1, #start
        JMP  r1

timer:  MOV  r1, #0x30
        MOV  byte [TIMER + 6], r1
        MOV  r1, #23
        MOV  byte [TIMER], r1
        MOV  r1, #0
        MOV  byte [TIMER], r1
        RET

h_tick: BSR  timer
        MOV  r1, [LOG + 4]
        ADD  r1, #1
        MOV  [LOG + 4], r1
        RTI

h_exit: MFUR r1, r6
        MOV  [LOG + 0], r1
        MOV  r1, #0x600D
        MOV  [LOG + 8], r1
        DI
        HALT

bad:    MOV  r1, [sp + 4]
        MOV  [LOG + 12], r1
        MOV  r1, #0xBAD
        MOV  [LOG + 8], r1
        DI
        HALT

start:  MOV  sp, #W + 0x20000
        MOV  r2, #1024 + (UCODE >> 12)
        MTSR 12, r2
        MOV  r3, #UCODE | 5
        MTSR 13, r3
        MOV  r2, #1024 + (UDATA >> 12)
        MTSR 12, r2
        MOV  r3, #UDATA | 3
        MTSR 13, r3
        MOV  r1, #1
        MTSR 14, r1
        MOV  r1, #UDATA + 0xF00
        MTUR sp, r1
        MOV  r1, #0x80000001
        MTSR 11, r1
        BSR  timer
        SPL  #0
        MOV  r1, #user
        PUSH r1
        MOV  r1, #0x40000000
        PUSH r1
        RTI

        .org UCODE
user:   MOV  r4, #UDATA
        MOV  r5, #0
        MOV  r6, #0
.l:     MOV  [r4 + 8], r5
        ADD  r6, [r4 + 8]
        SAVE r5-r6
        RESTORE r5-r6
        MOV  r1, r5
        LSL  r1, #3
        XOR  r6, r1
        ADD  r5, #1
        CMP  r5, #500
        BNE  .l
        SWI  #1
