; monitor: a tiny memory monitor driven by console input (draft 1a). All
; numbers are hex.
;
;   w ADDR WORD...        write 16-bit words from ADDR on
;   b ADDR BYTE...        write bytes
;   s ADDR text           write the text after one blank as bytes
;   f ADDR LEN BYTE       fill
;   c SRC DST LEN         copy (overlapping areas are fine)
;   d ADDR LEN            hex dump, 16 bytes a line
;   r ADDR                read one 16-bit word
;
; Every line is echoed after "> ". Anything wrong prints "?", and then the
; command has done nothing: all its arguments are parsed before it acts.
;
; Like the draft 0 monitor this one has 16-bit addresses and words: numbers
; are taken mod 2^16, and word accesses ignore address bit 0. Monitor
; address A is RAM address A. (A range that runs past FFFF carries on into
; the RAM above 64 KB instead of wrapping round to 0000, where this program
; lives; the addresses printed by d do wrap.)

;! input: "f 8000 80 2E\nw 8000 1234 ABCD 0 ffff\nb 8008 48 65 6C 6C 6F\ns 8010 Hello, monitor!\nd 8000 30\nc 8010 8021 7\nd 8020 10\nc 8000 8002 6\nd 8000 10\nr 8000\nr 8011\nx 1234\nd 8000\nw 8000 12G4\nd 8000 3 4\nb 8000\n\n  d   803E   5  \nb 8050 0 1 7F 80 FF 41 61 20 7E\nd 8050 9\nf 8060 5 41\nd 805E 8\nc 8061 8060 4\nd 8060 5\nw 8070 10000 BEEF\nr 8070\nd 8070 0\nr 8072"

        .include "lib/start.s"

LINESZ  = 80
MAXARGS = LINESZ / 2            ; a number and a blank need two characters

main:
.loop:  LEA  r1, line
        MVI  r2, LINESZ
        BSR  gets
        CMPI r1, -1
        BEQ  .eof
        LEA  r1, s_prompt
        BSR  puts
        LEA  r1, line
        BSR  puts
        BSR  newline
        BSR  command
        BRA  .loop
.eof:   RET

; command: run the command in `line`. The handlers get r8 pointing after the
; command letter and may use r8-r11, which command saves for them. A parse
; error anywhere jumps to `bail`, which unwinds the stack to here.
command:
        SAVE r8-r11
        ST   sp, [errsp]
        LEA  r8, line
        BSR  skipblanks
        BEQ  cmd_done           ; an empty line
        ADDI r8, 1
        ADDI r2, -'b'           ; the table runs from 'b' to 'w'
        CMPI r2, 'w' - 'b'
        BHI  bail               ; unsigned: catches below 'b' too
        LSL  r2, #2
        LD   r2, [cmdtab + r2]
        CALL r2
cmd_done:
        RESTORE r8-r11
        RET
bail:   LD   sp, [errsp]        ; back to command's stack level
        LEA  r1, s_what
        BSR  puts
        BRA  cmd_done

; ---- argument parsing (all work on the scan pointer r8) ----

; skipblanks: advance r8 to the next character that isn't a space or tab
; -> r2 = that character, Z set if it is the NUL at the end of the line.
skipblanks:
        LDB  r2, [r8]
        BEQ  .ret
        CMPI r2, ' '
        BEQ  .skip
        CMPI r2, 9
        BNE  .ret               ; (Z is clear here)
.skip:  ADDI r8, 1
        BRA  skipblanks
.ret:   RET

; hexnum: parse the hex number at r8 -> r1 = its value mod 2^16, r2 = the
; character after it, with r8 on that character. The number must have at
; least one digit and end at a blank or the end of the line, or it bails.
; Uses r1 and r2 only.
hexnum: MVI  r1, 0
        LDB  r2, [r8]
.digit: ADDI r2, -'0'
        CMPI r2, 9
        BLS  .add
        OR   r2, #0x20          ; 'A'-'F' -> 'a'-'f' (with '0' already off)
        ADDI r2, '0' - 'a'
        CMPI r2, 5
        BHI  bail
        ADDI r2, 10
.add:   LSL  r1, #4
        OR   r1, r2
        ADDI r8, 1
        LDB  r2, [r8]
        BEQ  .end
        CMPI r2, ' '
        BEQ  .end
        CMPI r2, 9
        BNE  .digit
.end:   ZXH  r1
        RET

; getargs: parse the rest of the line as hex numbers into `args`
; -> r1 = how many, r2 = args. Bails on a bad number.
getargs:
        LEA  r4, args           ; r4 = where the next one goes
.next:  BSR  skipblanks
        BEQ  .end
        BSR  hexnum
        ST   r1, [r4]
        ADDI r4, 4
        BRA  .next
.end:   LEA  r2, args
        MOV  r1, r4
        SUB  r1, r2
        LSR  r1, #2
        RET

; ---- the commands ----

cmd_w:  BSR  getargs
        CMPI r1, 2
        BLO  bail
        DEC  r1                 ; r1 = words to write
        LD   r3, [r2]           ; r3 = address
        AND  r3, #-2            ; word accesses ignore bit 0
.next:  ADDI r2, 4
        LD   r4, [r2]
        STH  r4, [r3]
        ADDI r3, 2
        DEC  r1
        BNE  .next
        RET

cmd_b:  BSR  getargs
        CMPI r1, 2
        BLO  bail
        DEC  r1                 ; r1 = bytes to write
        LD   r3, [r2]           ; r3 = address
.next:  ADDI r2, 4
        LD   r4, [r2]
        STB  r4, [r3]
        ADDI r3, 1
        DEC  r1
        BNE  .next
        RET

cmd_s:  BSR  skipblanks
        BSR  hexnum             ; r1 = address, r8 on the blank or NUL after it
        TST  r2, r2
        BEQ  .done              ; no blank: no text
        BRA  .next              ; skip exactly one blank
.copy:  STB  r2, [r1]
        ADDI r1, 1
.next:  ADDI r8, 1
        LDB  r2, [r8]
        BNE  .copy
.done:  RET

cmd_f:  BSR  getargs
        CMPI r1, 3
        BNE  bail
        LD   r1, [r2]           ; address
        LD   r3, [r2 + 4]       ; length
        LD   r2, [r2 + 8]       ; byte
        BRA  memset             ; tail call

cmd_c:  BSR  getargs
        CMPI r1, 3
        BNE  bail
        LD   r1, [r2 + 4]       ; destination
        LD   r3, [r2 + 8]       ; length
        LD   r2, [r2]           ; source
        BRA  memmove

cmd_r:  BSR  getargs
        CMPI r1, 1
        BNE  bail
        LD   r8, [r2]           ; r8 = address
        MOV  r1, r8
        MVI  r2, 4
        BSR  print_hex
        LEA  r1, s_eq
        BSR  puts
        AND  r8, #-2            ; word accesses ignore bit 0
        LDH  r1, [r8]
        MVI  r2, 4
        BSR  print_hex
        BRA  newline

; d: r8 = start of the line, r9 = end of the dump, r10 = end of the line,
; r11 walks the line.
cmd_d:  BSR  getargs
        CMPI r1, 2
        BNE  bail
        LD   r8, [r2]
        LD   r9, [r2 + 4]
        ADD  r9, r8             ; r9 = address + length
.line:  CMP  r8, r9
        BHS  .done
        LEA  r10, [r8 + 16]
        CMP  r10, r9
        BLS  .full
        MOV  r10, r9            ; a short last line
.full:  MOV  r1, r8
        MVI  r2, 4
        BSR  print_hex
        MVI  r1, ':'
        BSR  putc
        MOV  r11, r8
.hex:   BSR  space
        LDB  r1, [r11]
        MVI  r2, 2
        BSR  print_hex
        ADDI r11, 1
        CMP  r11, r10
        BLO  .hex
        LEA  r11, [r8 + 16]     ; r11 = columns missing on a short line
        SUB  r11, r10
        BEQ  .text0
.pad:   LEA  r1, s_pad          ; keep the text column lined up
        BSR  puts
        DEC  r11
        BNE  .pad
.text0: BSR  space
        BSR  space
        MOV  r11, r8
.text:  LDB  r1, [r11]
        CMPI r1, ' '
        BLO  .dot
        CMPI r1, 0x7E
        BLS  .char
.dot:   MVI  r1, '.'
.char:  BSR  putc
        ADDI r11, 1
        CMP  r11, r10
        BLO  .text
        BSR  newline
        MOV  r8, r10
        BRA  .line
.done:  RET

        .align 4
cmdtab: .word cmd_b, cmd_c, cmd_d, bail, cmd_f                  ; b-f
        .word bail, bail, bail, bail, bail, bail                ; g-l
        .word bail, bail, bail, bail, bail, cmd_r, cmd_s        ; m-s
        .word bail, bail, bail, cmd_w                           ; t-w
errsp:  .word 0
args:   .space 4 * MAXARGS
s_prompt: .asciz "> "
s_what: .asciz "?\n"
s_eq:   .asciz " = "
s_pad:  .asciz "   "
line:   .space LINESZ
        .align 2

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/string.s"
