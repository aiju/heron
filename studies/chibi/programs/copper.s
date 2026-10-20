; copper: the copper's test. Its list writes to the suite's console at
; two lines of each frame, A at 100 and B at 200; the program meanwhile
; waits for line 300 twice (the scanline at the interrupt controller's
; +6), then turns the copper off and prints Z: ABABZ. The list's place is
; the word at COPPTR; a WAIT's low half is written at +6 (bit 15: CEN).

IRQC    = 0xFFFFD000
CONSOLE = 0xFFFFFF00
COPPTR  = 0x60

        .org 0
        MOV  sp, #0x100000
        MOV  r5, #IRQC
        MOV  r7, #CONSOLE
        LEA  r1, [list]
        MOV  [COPPTR], r1
        MOV  r1, #0x8000 + 100          ; the copper on, from line 100
        MOV  half [r5 + 6], r1
        MOV  r6, #2
.frame: MOV  r1, half [r5 + 6]          ; wait for line 300 ...
        CMP  r1, #300
        BNE  .frame
.out:   MOV  r1, half [r5 + 6]          ; ... and for it to end
        CMP  r1, #300
        BEQ  .out
        DBNZ r6, .frame
        MOV  r1, #0
        MOV  half [r5 + 6], r1          ; the copper off
        MOV  r1, #'Z'
        MOV  byte [r7], r1
        HALT

        .align 4
list:   .word 0xFFFFF000, 'A'           ; MOVE console, 'A'
        .word 0x8000 + 200              ; WAIT 200
        .word 0xFFFFF000, 'B'
        .word 0x8000 + 100              ; WAIT 100 (the next frame's)
        .word 0x40000000 + list         ; JUMP list
