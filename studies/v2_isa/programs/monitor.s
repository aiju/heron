; monitor: a tiny memory monitor driven by console input. All numbers are
; hex.
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

;! input-file: ../../v1_isa/programs/common/monitor.txt

        .include "lib/start.s"

LINESZ  = 80
MAXARGS = LINESZ / 2            ; a number and a blank need two characters

main:
.loop:  LEA  r1, [line]
        MOV  r2, #LINESZ
        BSR  gets
        CMP  r1, #-1
        BEQ  .eof
        LEA  r1, [s_prompt]
        BSR  puts
        LEA  r1, [line]
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
        MOV  [errsp], sp
        LEA  r8, [line]
        BSR  skipblanks
        BEQ  cmd_done           ; an empty line
        SUB  r2, #'b'           ; the table runs from 'b' to 'w'
        CMP  r2, #'w' - 'b'
        BHI  bail               ; unsigned: catches below 'b' too
        LSL  r2, #2
        CALL [cmdtab + r2]
cmd_done:
        RESTORE r8-r11
        RET
bail:   MOV  sp, [errsp]        ; back to command's stack level
        LEA  r1, [s_what]
        BSR  puts
        BRA  cmd_done

; ---- argument parsing (all work on the scan pointer r8) ----

; skipblanks: r2 = the next character that isn't a space or tab, r8 points
; after it. Z is set if it is the NUL at the end of the line.
skipblanks:
        MOVS r2, byte [r8]+
        BEQ  .ret
        CMP  r2, #' '
        BEQ  skipblanks
        CMP  r2, #9
        BEQ  skipblanks
.ret:   RET

; hexnum: parse a hex number whose first character is in r2 (r8 points after
; it) -> r1 = its value mod 2^16. It must have at least one digit and end at
; a blank or the end of the line, or it bails. Leaves r8 after the blank, or
; on the NUL. Uses r1 and r2 only.
hexnum: MOV  r1, #0
.digit: SUB  r2, #'0'
        CMP  r2, #9
        BLS  .add
        OR   r2, #0x20          ; 'A'-'F' -> 'a'-'f' (with '0' already off)
        SUB  r2, #'a' - '0'
        CMP  r2, #5
        BHI  bail
        ADD  r2, #10
.add:   LSL  r1, #4
        OR   r1, r2
        MOVS r2, byte [r8]+
        BEQ  .nul
        CMP  r2, #' '
        BEQ  .end
        CMP  r2, #9
        BNE  .digit
.end:   ZXH  r1
        RET
.nul:   DEC  r8                 ; stay on the NUL
        BRA  .end

; getargs: parse the rest of the line as hex numbers into `args`
; -> r1 = how many, r2 = args. Bails on a bad number.
getargs:
        LEA  r4, [args]         ; r4 = where the next one goes
.next:  BSR  skipblanks
        BEQ  .end
        BSR  hexnum
        MOV  [r4]+, r1
        BRA  .next
.end:   LEA  r2, [args]
        MOV  r1, r4
        SUB  r1, r2
        LSR  r1, #2
        RET

; ---- the commands ----

cmd_w:  BSR  getargs
        CMP  r1, #2
        BLO  bail
        DEC  r1                 ; r1 = words to write
        MOV  r3, [r2]+          ; r3 = address
        AND  r3, #-2            ; word accesses ignore bit 0
.next:  MOV  r4, [r2]+
        MOV  half [r3], r4
        ADD  r3, #2
        DBNZ r1, .next
        RET

cmd_b:  BSR  getargs
        CMP  r1, #2
        BLO  bail
        DEC  r1                 ; r1 = bytes to write
        MOV  r3, [r2]+          ; r3 = address
.next:  MOV  r4, [r2]+
        MOV  byte [r3]+, r4
        DBNZ r1, .next
        RET

cmd_s:  BSR  skipblanks
        BSR  hexnum             ; r1 = address; r8 is past exactly one blank
        BRA  .next
.copy:  MOV  byte [r1]+, r2
.next:  MOVS r2, byte [r8]+
        BNE  .copy
        RET

cmd_f:  BSR  getargs
        CMP  r1, #3
        BNE  bail
        MOV  r1, [r2]+          ; address
        MOV  r3, [r2]+          ; length
        MOV  r2, [r2]           ; byte
        BRA  memset             ; tail call

cmd_c:  BSR  getargs
        CMP  r1, #3
        BNE  bail
        MOV  r4, [r2]+          ; source
        MOV  r1, [r2]+          ; destination
        MOV  r3, [r2]           ; length
        MOV  r2, r4
        BRA  memmove

cmd_r:  BSR  getargs
        CMP  r1, #1
        BNE  bail
        MOV  r8, [r2]           ; r8 = address
        MOV  r1, r8
        MOV  r2, #4
        BSR  print_hex
        LEA  r1, [s_eq]
        BSR  puts
        AND  r8, #-2            ; word accesses ignore bit 0
        MOV  r1, half [r8]
        MOV  r2, #4
        BSR  print_hex
        BRA  newline

; d: r8 = start of the line, r9 = end of the dump, r10 = end of the line,
; r11 walks the line.
cmd_d:  BSR  getargs
        CMP  r1, #2
        BNE  bail
        MOV  r8, [r2]+
        MOV  r9, r8
        ADD  r9, [r2]           ; r9 = address + length
.line:  CMP  r8, r9
        BHS  .done
        LEA  r10, [r8 + 16]
        CMP  r10, r9
        BLS  .full
        MOV  r10, r9            ; a short last line
.full:  MOV  r1, r8
        MOV  r2, #4
        BSR  print_hex
        MOV  r1, #':'
        BSR  putc
        MOV  r11, r8
.hex:   BSR  space
        MOV  r1, byte [r11]+
        MOV  r2, #2
        BSR  print_hex
        CMP  r11, r10
        BLO  .hex
        LEA  r11, [r8 + 16]     ; r11 = columns missing on a short line
        SUB  r11, r10
        BEQ  .text0
.pad:   LEA  r1, [s_pad]        ; keep the text column lined up
        BSR  puts
        DBNZ r11, .pad
.text0: BSR  space
        BSR  space
        MOV  r11, r8
.text:  MOV  r1, byte [r11]+
        CMP  r1, #' '
        BLO  .dot
        CMP  r1, #0x7E
        BLS  .char
.dot:   MOV  r1, #'.'
.char:  BSR  putc
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
