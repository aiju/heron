; Console I/O for the system (draft 1b on the system bus): the same
; routines and contracts as the v1_isa study's lib/console.s, on the UART
; primitives in lib/start.s.
;
;   putc     r1 = character                      -> (nothing)             clobbers nothing
;   getc                                         -> r1 = byte 0-255, or -1 at end of input
;                                                   (N and Z from r1)
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

        .align 2

putc:   BRA  __con_putc

getc:   BRA  __con_getc

newline:
        MOV  r1, #10
        BRA  __con_putc

space:  MOV  r1, #' '
        BRA  __con_putc

puts:   MOV  r3, r1
        BRA  .next
.loop:  BSR  __con_putc
.next:  MOV  r1, byte [r3]+     ; sets Z at the NUL
        BNE  .loop
        RET

gets:   MOV  r5, r1             ; r5 = the buffer
        MOV  r3, r1             ; r3 = where the next character goes
        ADD  r2, r1
        DEC  r2                 ; r2 = last byte of the buffer, kept for the NUL
        BSR  __con_getc
        BPL  .have              ; got a byte: there is a line
        ST   r0, byte [r5]      ; no input at all: an empty string, and
        MOV  r1, #-1            ; -1 for end of input
        RET
.loop:  BSR  __con_getc
        BMI  .end               ; end of input also ends the last line
.have:  CMP  r1, #10
        BEQ  .end
        CMP  r3, r2
        BHS  .loop              ; buffer full: drop the character
        ST   r1, byte [r3]+
        BRA  .loop
.end:   ST   r0, byte [r3]
        SUB  r3, r5             ; length = end - start
        MOV  r1, r3
        RET
