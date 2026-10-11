; Startup code and vector table. Include this first; define `main`.
; main returns -> HALT. IRQs are ignored (RTI); traps print "TRAP" and halt.

        .org 0x0000
        JMP  __start            ; reset vector
        .org 0x0004
        RTI                     ; IRQ vector (unused by default)
        .org 0x0008
        JMP  __trap             ; trap vector (SWI, reserved opcodes)

__start:
        LI   sp, #0xFF00
        CALL main
        HALT

__trap:
        MVI  r1, 'T'
        STB  r1, [0xFF00]
        MVI  r1, 'R'
        STB  r1, [0xFF00]
        MVI  r1, 'A'
        STB  r1, [0xFF00]
        MVI  r1, 'P'
        STB  r1, [0xFF00]
        MVI  r1, 10
        STB  r1, [0xFF00]
        HALT
