; Console I/O.
;
;   putc     r1 = character                      -> (nothing)
;   getc                                         -> r1 = byte, or -1 at end of input
;   puts     r1 = NUL-terminated string          -> r1 = address of the NUL
;   newline                                      -> (prints "\n")
;   space                                        -> (prints " ")
;   gets     r1 = buffer, r2 = buffer size       -> r1 = line length, or -1 at end of input
;
; Everything here only touches r1-r4. No other library file is needed.

CONSOLE = 0xFF00                ; console data register (read: input, write: output)

        .align 2

putc:   STB  r1, [CONSOLE]
        RET

; The console returns FFFF when no input is waiting. The simulator preloads all
; input, so "nothing waiting" means end of input, and FFFF is exactly -1.
getc:   LD   r1, [CONSOLE]
        RET

puts:   LDB  r2, [r1]           ; loads set Z: no compare needed
        BEQ  .done
        STB  r2, [CONSOLE]
        INC  r1
        BRA  puts
.done:  RET

newline:
        MVI  r1, 10
        STB  r1, [CONSOLE]
        RET

space:  MVI  r1, ' '
        STB  r1, [CONSOLE]
        RET

; gets: read one line (without the '\n') into the buffer at r1 and NUL-terminate
; it. At most r2-1 characters are stored; the rest of a long line is dropped.
; Returns the number of characters stored, or -1 if the input was already at
; its end. A last line without '\n' still counts as a line.
gets:   MOV  r3, r1             ; r3 = write pointer
        ADD  r2, r1
        DEC  r2                 ; r2 = last usable byte (room for the NUL)
        LD   r4, [CONSOLE]
        CMPI r4, -1
        BNE  .have
        MVI  r1, -1             ; nothing at all: end of input
        RET
.loop:  LD   r4, [CONSOLE]
        CMPI r4, -1
        BEQ  .end
.have:  CMPI r4, 10
        BEQ  .end
        CMP  r3, r2
        BHS  .loop              ; buffer full: drop the character
        STB  r4, [r3]
        INC  r3
        BRA  .loop
.end:   STB  r0, [r3]
        SUB  r3, r1
        MOV  r1, r3
        RET
