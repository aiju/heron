; irqtest: the timer's interrupt on Reed, the same at chip level as on the
; model whenever it comes: the vector it reaches, sr in the handler and as
; pushed, IPL, and the controller's registers, logged at LOG
W       = 0x80000000
TIMER   = 0xC0002000
IC      = 0xC0005800
LOG     = W + 0x10000

        .org W + 0x00
        JMP  boot
        .org W + 0x54
        JMP  h_tick             ; level 6
        .org W + 0x200
boot:   MOV  r1, #start
        JMP  r1

h_tick: MOV  r1, [sp]           ; the pushed sr
        MOV  [LOG + 0], r1
        MFSR r1, sr             ; in the handler: S, IPL 6, I clear
        MOV  [LOG + 4], r1
        MOV  r1, half [IC + 4]  ; the status register
        AND  r1, #0x0F0000F0
        MOV  [LOG + 8], r1
        MOV  r1, #0x30          ; stop the timer's request: a new count
        MOV  byte [TIMER + 6], r1
        MOV  r1, #0xFF
        MOV  byte [TIMER], r1
        MOV  byte [TIMER], r1
        MOV  r1, [count]
        ADD  r1, #1
        MOV  [count], r1
        RTI

start:  MOV  sp, #W + 0x20000
        MOV  r1, #0x30          ; counter 0, LSB then MSB, mode 0
        MOV  byte [TIMER + 6], r1
        MOV  r1, #40
        MOV  byte [TIMER], r1
        MOV  r1, #0
        MOV  byte [TIMER], r1
        SPL  #2
        EI
.w:     MOV  r1, [count]
        CMP  r1, #0
        BEQ  .w
        MFSR r1, sr
        MOV  [LOG + 12], r1
        DI
        MOV  r1, #0x1234
        MOV  [LOG + 16], r1
        HALT
        .align 4
count:  .word 0
