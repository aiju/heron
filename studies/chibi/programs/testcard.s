; testcard: Chibi Heron's first program, for the board itself (RFC 0047):
; nothing but the board's own devices, no test fixture.
;
; - A banner on UART 0, at the 115,200 baud, 8N1 the reset routine leaves.
; - The palette's first 16 colours (VGA's), and a test card in frame
;   buffer 0: a blue ground with a white border, sixteen colour bars,
;   CHIBI HERON, and the seconds since it started.
; - The display on and the frame interrupt counting frames: at every
;   60th the seconds move on, and the main loop redraws them.
; - A beep at the start: 0.2 s of a 1 kHz square wave, which the device
;   task plays at 8 kHz from a buffer; then the timer's counter 1 stops.
; - What's typed, echoed to UART 0: UART 0's characters as they come
;   (a return as CR LF), the keyboard's scan codes in hex, from a ring
;   the keyboard's interrupt fills.
;
; It never stops. The main loop polls rather than HALTs: HALT's wait
; isn't a task point, so while it waited the device task couldn't take
; the keyboard's clock edges.

        .include "lib/board.s"

STACK   = FB0                   ; the stack grows down from the frame buffers
SAMPLES = 0x10000               ; the beep's samples
BEEP_N  = 1600                  ; 0.2 s at 8 kHz
GROUND  = 0x11111111            ; eight pixels of colour 1, the ground
TEXT_Y  = 72
BARS_Y  = 176                   ; the bars' first line, and how many
BARS_N  = 192
SECS_X  = 272                   ; the seconds' counter: 4 digits
SECS_Y  = 400

; ---- the vectors: 4 bytes each, room for a JMP
        .org V_RESET
        JMP  start
        .org V_IRQ
        RTI                     ; an interrupt with no source pending
        .org V_ILLEGAL
        JMP  fatal
        .org V_SWI
        JMP  fatal
        .org V_DIV
        JMP  fatal
        .org V_ADDR
        JMP  fatal
        .org V_TAG
        JMP  fatal
        .org V_TIMER
        JMP  fatal              ; (the sources it doesn't turn on)
        .org V_FRAME
        JMP  frame_isr
        .org V_UART0
        JMP  fatal
        .org V_UART1
        JMP  fatal
        .org V_KBD
        JMP  kbd_isr
        .org V_MOUSE
        JMP  fatal
        .org V_CF
        JMP  fatal
        .org V_BUTTON
        JMP  fatal
        .org COPPTR
        .space 0x20             ; the tasks' words, 0x60-0x7F

start:  MOV  sp, #STACK
        MOV  r12, #0                    ; (reset leaves the registers as they were)
        LEA  r10, [banner]
        CALL puts
        CALL palette
        CALL card
        CALL beep
        MOV  r1, #VC_DEN + VC_VIE       ; frame buffer 0 shown, the frame interrupt on
        MOV  half [VIDEO], r1
        EI

; ---- the main loop
main:   MOV  r1, byte [UART0 + U_LSR]
        AND  r1, #1                     ; a character in
        BEQ  .keys
        MOV  r1, byte [UART0 + U_RBR]
        CALL putc
        CMP  r1, #13
        BNE  .keys
        MOV  r1, #10                    ; a return: CR LF
        CALL putc
.keys:  MOV  r2, [kbd_tail]
        CMP  r2, [kbd_head]
        BEQ  .secs
        MOV  r1, byte [kbd_ring + r2]
        INC  r2
        AND  r2, #15
        MOV  [kbd_tail], r2
        CALL puthex2
        MOV  r1, #' '
        CALL putc
.secs:  MOV  r1, [seconds]
        CMP  r1, [shown]
        BEQ  .beep
        MOV  [shown], r1
        CALL draw_secs
.beep:  TST  r12, r12                   ; r12: the beep is over
        BNE  main
        MOV  r1, [PCMPTR]
        CMP  r1, [PCMEND]
        BNE  main
        MOV  r1, #0x70                  ; counter 1 to mode 0: OUT1 low, no more requests
        MOV  byte [T_CTL], r1
        MOV  r12, #1
        BRA  main

; ---- the interrupts

frame_isr:
        PUSH r1
        MOV  r1, #VC_DEN + VC_VIE
        MOV  half [VIDEO], r1           ; any write acknowledges the frame interrupt
        INC  [frames]
        MOV  r1, [frames]
        CMP  r1, #60
        BLO  .done
        CLR  [frames]
        INC  [seconds]
.done:  POP  r1
        RTI

kbd_isr:
        SAVE r1-r2
        MOV  r1, half [KBDFRAME]        ; the device task's frame: the data in bits 13-6
        LSR  r1, #6
        AND  r1, #0xFF
        MOV  r2, [kbd_head]
        MOV  byte [kbd_ring + r2], r1
        INC  r2
        AND  r2, #15
        MOV  [kbd_head], r2
        MOV  r1, #0
        MOV  byte [PS2_KCTL], r1        ; the interrupt cleared, the pulls off
        RESTORE r1-r2
        RTI

; fatal: an exception, or an interrupt it didn't ask for. It prints where
; (the return address the entry pushed above the flags word) and stops;
; the halt button then takes it to ODT.
fatal:  DI
        LEA  r10, [.msg]
        CALL puts
        MOV  r1, [sp + 4]
        CALL puthex8
        LEA  r10, [crlf]
        CALL puts
        HALT
.msg:   .asciz "\r\nfatal: an exception or a stray interrupt, returning to "
        .align 2

; ---- UART 0

; putc: r1 = a character. Clobbers r0.
putc:   MOV  r0, byte [UART0 + U_LSR]
        AND  r0, #0x20                  ; THR empty
        BEQ  putc
        MOV  byte [UART0 + U_RBR], r1
        RET

; puts: r10 = a NUL-terminated string. Clobbers r0, r1, r10.
puts:   MOVS r1, byte [r10]+
        BEQ  .done
.wait:  MOV  r0, byte [UART0 + U_LSR]
        AND  r0, #0x20
        BEQ  .wait
        MOV  byte [UART0 + U_RBR], r1
        BRA  puts
.done:  RET

; puthex2, puthex8: r1 = a value, its low 2 or 8 hex digits. Clobbers r0-r3.
puthex2:
        MOV  r3, #2
        ROR  r1, #8
        BRA  puthex
puthex8:
        MOV  r3, #8
puthex: MOV  r2, r7
        MOV  r9, r1
.digit: ROR  r9, #28                    ; the next digit to bits 3-0
        MOV  r1, r9
        AND  r1, #15
        MOV  r1, byte [hexdigits + r1]
        CALL putc
        DBNZ r3, .digit
        JMP  r2

; ---- the picture

; palette: the first 16 colours, VGA's, and the pixel mask.
palette:
        MOV  r1, #0xFF
        MOV  byte [PAL_MASK], r1        ; all eight of the pixel's bits
        MOV  r1, #0
        MOV  byte [PAL_WADDR], r1
        LEA  r2, [vga16]
        MOV  r3, #48                    ; red, green, blue for each
.next:  MOV  r1, byte [r2]+
        MOV  byte [PAL_DATA], r1
        DBNZ r3, .next
        RET

; card: the test card in frame buffer 0.
card:   PUSH r7
        ; the ground: all 480 lines (the 512 bytes of each)
        MOV  r1, #FB0
        MOV  r2, #GROUND
        MOV  r3, #480 * LINE / 4
.ground:
        MOV  [r1]+, r2
        DBNZ r3, .ground
        ; sixteen bars of 40 pixels, a colour each
        MOV  r1, #FB0 + LINE * BARS_Y
        MOV  r4, #BARS_N
.line:  MOV  r2, r1
        MOV  r5, #0                     ; eight pixels of the bar's colour
        MOV  r6, #16
.bar:   MOV  [r2]+, r5                  ; 40 pixels: 5 words
        MOV  [r2]+, r5
        MOV  [r2]+, r5
        MOV  [r2]+, r5
        MOV  [r2]+, r5
        ADD  r5, #0x11111111
        DBNZ r6, .bar
        ADD  r1, #LINE
        DEC  r4
        BNE  .line
        ; the border: 4 lines at the top and the bottom, 4 pixels at the sides
        MOV  r2, #-1                    ; colour 15
        MOV  r1, #FB0
        CALL hline4
        MOV  r1, #FB0 + LINE * 476
        CALL hline4
        MOV  r1, #FB0
        MOV  r3, #480
.side:  MOV  half [r1], r2
        MOV  half [r1 + 318], r2
        ADD  r1, #LINE
        DBNZ r3, .side
        ; the name
        LEA  r10, [name]
        MOV  r2, #188                   ; centred: 11 characters of 24 pixels
        MOV  r3, #TEXT_Y
        CALL draw_string
        CALL draw_secs
        POP  r7
        RET

; hline4: r1 = a line's first byte, r2 = 8 pixels: 4 lines of them.
hline4: MOV  r3, #4 * LINE / 4
.word:  MOV  [r1]+, r2
        DBNZ r3, .word
        RET

; draw_secs: the seconds, 4 digits at SECS_X, SECS_Y, on the ground.
draw_secs:
        PUSH r7
        MOV  r1, #FB0 + LINE * SECS_Y + SECS_X / 2
        MOV  r2, #GROUND
        MOV  r3, #28                    ; the digits' lines
.erase: MOV  r4, r1
        MOV  r5, #12                    ; 96 pixels
.word:  MOV  [r4]+, r2
        DBNZ r5, .word
        ADD  r1, #LINE
        DBNZ r3, .erase
        MOV  r1, [seconds]
        MOV  r5, #10
        LEA  r10, [digits + 4]          ; the digits, last first
        CLR  byte [r10]
        MOV  r6, #4
.div:   DIVU r0:r1, r5
        ADD  r0, #'0'
        DEC  r10
        MOV  byte [r10], r0
        DBNZ r6, .div
        MOV  r2, #SECS_X
        MOV  r3, #SECS_Y
        CALL draw_string
        POP  r7
        RET

; draw_string: r10 = a NUL-terminated string, at (r2, r3), each character
; 24 pixels on. Clobbers r0, r1, r2, r4-r10.
draw_string:
        PUSH r7
.next:  MOVS r1, byte [r10]+
        BEQ  .done
        CALL draw_char
        ADD  r2, #24
        BRA  .next
.done:  POP  r7
        RET

; draw_char: r1 = a character, '0'-'Z' or a space, at (r2, r3), r2 even:
; its 5 x 7 glyph in colour 15, each dot 4 x 4 pixels. Clobbers r0, r1,
; r4-r9.
draw_char:
        SUB  r1, #'0'
        BLO  .done                      ; a space (or anything below '0')
        CMP  r1, #'Z' - '0'
        BHI  .done
        MOV  r4, r1
        LSL  r4, #3
        SUB  r4, r1                     ; 7 bytes a glyph
        LEA  r4, [font + r4]
        MOV  r5, r3
        LSL  r5, #9                     ; 512 bytes a line
        MOV  r6, r2
        LSR  r6, #1
        ADD  r5, r6
        ADD  r5, #FB0                   ; the glyph's top left byte
        MOV  r8, #-1                    ; four pixels of colour 15
        MOV  r6, #7
.row:   MOVS r1, byte [r4]+
        LSL  r1, #27                    ; the leftmost dot to bit 31
        MOV  r0, r5
        MOV  r9, #5
.dot:   LSL  r1, #1                     ; C: this dot
        BCC  .skip
        MOV  half [r0], r8
        MOV  half [r0 + LINE], r8
        MOV  half [r0 + 2 * LINE], r8
        MOV  half [r0 + 3 * LINE], r8
.skip:  ADD  r0, #2
        DBNZ r9, .dot
        ADD  r5, #4 * LINE
        DEC  r6
        BNE  .row
.done:  RET

; ---- the sound

; beep: 0.2 s of a 1 kHz square wave, for the device task to play: its
; samples, PCMPTR and PCMEND, and counter 1 at 8 kHz (mode 3, a square
; wave, OUT1 the sample clock).
beep:   MOV  r1, #SAMPLES
        MOV  r2, #BEEP_N / 8
        MOV  r3, #0xC0C0C0C0            ; four samples high
        MOV  r4, #0x40404040            ; and four low
.fill:  MOV  [r1]+, r3
        MOV  [r1]+, r4
        DBNZ r2, .fill
        MOV  r1, #SAMPLES
        MOV  [PCMPTR], r1
        ADD  r1, #BEEP_N
        MOV  [PCMEND], r1
        MOV  r1, #0x76                  ; counter 1: LSB then MSB, mode 3
        MOV  byte [T_CTL], r1
        MOV  r1, #230                   ; 1.8432 MHz / 230: 8014 Hz
        MOV  byte [T_C1], r1
        MOV  r1, #0
        MOV  byte [T_C1], r1
        RET

; ---- data

banner: .asciz "\r\nChibi Heron test card\r\n"
crlf:   .asciz "\r\n"
name:   .asciz "CHIBI HERON"
hexdigits:
        .ascii "0123456789ABCDEF"
vga16:  .byte 0, 0, 0,  0, 0, 42,  0, 42, 0,  0, 42, 42
        .byte 42, 0, 0,  42, 0, 42,  42, 21, 0,  42, 42, 42
        .byte 21, 21, 21,  21, 21, 63,  21, 63, 21,  21, 63, 63
        .byte 63, 21, 21,  63, 21, 63,  63, 63, 21,  63, 63, 63
        .include "lib/font5x7.s"

        .align 4
frames: .word 0                         ; frames this second
seconds: .word 0
shown:  .word -1                        ; the seconds drawn
kbd_head: .word 0                       ; the keyboard's ring: kbd_isr's end,
kbd_tail: .word 0                       ; and the main loop's
kbd_ring: .space 16
digits: .space 8
