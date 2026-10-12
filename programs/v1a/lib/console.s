; Console I/O (draft 1a).
;
;   putc     r1 = character                      -> (nothing)             clobbers nothing
;   getc                                         -> r1 = byte 0-255, or -1 at end of input
;   puts     r1 = NUL-terminated string          -> (nothing)             clobbers r1-r3
;   newline                                      -> prints "\n"           clobbers r1
;   space                                        -> prints " "            clobbers r1
;   gets     r1 = buffer, r2 = size (>= 1)       -> r1 = line length without the '\n',
;                                                   or -1 at end of input  clobbers r1-r5
;
; gets stores at most size-1 characters and always NUL-terminates the buffer
; (at the end of input it leaves an empty string). The rest of an over-long
; line is read and dropped; the length returned is what was stored. A last
; line without '\n' still counts as a line.
;
; The console data register reads as a 32-bit word: the next input byte
; (0-255), or -1 when no input is left. So a word load sets N exactly at the
; end of input, and no compare is needed. (A byte load would read 0xFF for
; both -1 and a real 0xFF byte.)
;
; Only r1-r5 are touched. No other library file is needed.

CONSOLE = 0xFFFFFF00            ; reachable as a sign-extended 16-bit absolute address

        .align 2

putc:   STB  r1, [CONSOLE]
        RET

getc:   LD   r1, [CONSOLE]
        RET

newline:
        MVI  r1, 10
        STB  r1, [CONSOLE]
        RET

space:  MVI  r1, ' '
        STB  r1, [CONSOLE]
        RET

; The console address goes in a register, so the loop is four one-parcel
; instructions per character (an absolute STB would be two parcels).
puts:   LI   r3, #CONSOLE
        BRA  .next
.loop:  STB  r2, [r3]
        ADDI r1, 1
.next:  LDB  r2, [r1]           ; loads set Z: stop at the NUL
        BNE  .loop
        RET

gets:   LI   r5, #CONSOLE
        MOV  r3, r1             ; r3 = where the next character goes
        ADD  r2, r1
        ADDI r2, -1             ; r2 = last byte of the buffer, kept for the NUL
        LD   r4, [r5]
        BPL  .have              ; got a byte: there is a line
        STB  r0, [r1]           ; no input at all: an empty string, and
        MVI  r1, -1             ; -1 for end of input
        RET
.loop:  LD   r4, [r5]
        BMI  .end               ; end of input also ends the last line
.have:  CMPI r4, 10
        BEQ  .end
        CMP  r3, r2
        BHS  .loop              ; buffer full: drop the character
        STB  r4, [r3]
        ADDI r3, 1
        BRA  .loop
.end:   STB  r0, [r3]
        SUB  r3, r1             ; length = end - start
        MOV  r1, r3
        RET
