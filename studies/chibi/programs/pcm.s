; pcm: eight samples played by the device task (RFC 0047). The buffer's
; bounds go to PCMPTR and PCMEND, then the timer's counter 1 is set to
; the sample rate (mode 3, a square wave; a count of 20: 10.9 us a sample); once the task
; has played them all (PCMPTR at PCMEND) the program prints P. The task
; goes on writing 0x80, the middle, at each request. The code is above
; the words the tasks keep at 0x60-0x73.

SLOW    = 0xFFFFA000            ; the timer at +0 (counter 1 +2, control +6)
CONSOLE = 0xFFFFFF00
PCMPTR  = 0x64
PCMEND  = 0x68

        .org 0
        JMP  start
        .org 0x100
start:  MOV  sp, #0x100000
        MOV  r5, #SLOW
        MOV  r7, #CONSOLE
        LEA  r1, [samples]
        MOV  [PCMPTR], r1
        ADD  r1, #8
        MOV  [PCMEND], r1
        MOV  r1, #0x76          ; counter 1: LSB then MSB, mode 3
        MOV  byte [r5 + 6], r1
        MOV  r1, #20
        MOV  byte [r5 + 2], r1
        MOV  r1, #0
        MOV  byte [r5 + 2], r1
.wait:  MOV  r1, [PCMPTR]
        MOV  r2, [PCMEND]
        CMP  r1, r2
        BNE  .wait
        MOV  r1, #'P'
        MOV  byte [r7], r1
        HALT

samples: .byte 0x80, 0xC0, 0xFF, 0xC0, 0x80, 0x40, 0x00, 0x40
