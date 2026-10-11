; Hardware interrupt test: timer IRQ every 300 cycles, an ISR counts ticks,
; the main program counts loop iterations and waits with HALT. Output is
; independent of exact timing.

        .org 0
        JMP  start
        .org 4
        JMP  isr
        .org 8
        HALT

isr:    PUSH r1
        LD   r1, [ticks]
        INC  r1
        ST   r1, [ticks]
        ST   r1, [0xFF06]       ; acknowledge the timer
        POP  r1
        RTI

start:  LI   sp, #0xF000
        LI   r1, #300
        ST   r1, [0xFF04]       ; timer period
        EI
.busy:  ADDI r2, 1              ; work while ticks < 3
        LD   r3, [ticks]
        CMPI r3, 3
        BLO  .busy
.wait:  HALT                    ; with I=1 this waits for the next interrupt
        LD   r3, [ticks]
        CMPI r3, 8
        BLO  .wait
        DI
        ST   r0, [0xFF04]       ; timer off
        MVI  r1, 'o'
        STB  r1, [0xFF00]
        MVI  r1, 'k'
        STB  r1, [0xFF00]
        MVI  r1, 10
        STB  r1, [0xFF00]
        MVI  r2, 0              ; clear the timing-dependent counter
        HALT

ticks:  .word 0
