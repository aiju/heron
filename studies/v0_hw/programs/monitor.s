; monitor: a tiny memory monitor driven by console input. All numbers are hex.
;
;   w ADDR WORD...        write words from ADDR on
;   b ADDR BYTE...        write bytes
;   s ADDR text           write the text after one blank as bytes
;   f ADDR LEN BYTE       fill
;   c SRC DST LEN         copy (overlapping areas are fine)
;   d ADDR LEN            hex dump, 16 bytes a line
;   r ADDR                read one word
;
; Every line is echoed after "> ". Anything wrong prints "?".

;! input-file: ../../v1_isa/programs/common/monitor.txt

        .include "lib/start.s"

LINESZ = 80

main:
.loop:  LI   r1, #line
        MVI  r2, LINESZ
        CALL gets
        CMPI r1, -1
        BEQ  .eof
        LI   r1, #s_prompt
        CALL puts
        LI   r1, #line
        CALL puts
        CALL newline
        BSR  command
        BRA  .loop
.eof:   RET

; command: run the command in `line`. Handlers parse their arguments from r8
; (advancing it) and may use r9-r11, which command saves for them. A parse
; error anywhere jumps to `bail`, which unwinds the stack to here.
command:
        PUSH r8
        PUSH r9
        PUSH r10
        PUSH r11
        ST   sp, [errsp]
        LI   r8, #line
        BSR  skipblanks
        LDB  r1, [r8]
        BEQ  cmd_done           ; empty line
        INC  r8
        LI   r2, #cmdtab
.find:  LDB  r3, [r2]
        BEQ  bail               ; not in the table
        CMP  r3, r1
        BEQ  .found
        ADDI r2, 4
        BRA  .find
.found: LD   r3, [r2 + 2]
        CALL r3
cmd_done:
        POP  r11
        POP  r10
        POP  r9
        POP  r8
        RET
bail:   LD   sp, [errsp]        ; back to command's stack level
        LI   r1, #s_what
        CALL puts
        BRA  cmd_done

; ---- argument parsing (all work on r8) ----
; (placed between command and the handlers so that every BSR to them is
; within the +-256 byte branch range)

; hexarg: skip blanks and parse a hex number -> r1. It must have at least one
; digit and end at a blank or the end of the line; otherwise bail.
hexarg: BSR  skipblanks
        MVI  r1, 0
        MVI  r3, 0              ; digits seen
.digit: LDB  r2, [r8]
        MOV  r4, r2
        ADDI r4, -'0'
        CMPI r4, 9
        BLS  .add
        OR   r2, #0x20          ; A-F -> a-f
        ADDI r2, -'a'
        CMPI r2, 5
        BHI  .end
        MOV  r4, r2
        ADDI r4, 10
.add:   SHL  r1                 ; no multi-bit shift: four single ones
        SHL  r1
        SHL  r1
        SHL  r1
        OR   r1, r4
        INC  r3
        INC  r8
        BRA  .digit
.end:   TST  r3, r3
        BEQ  .bad
        LDB  r2, [r8]
        BEQ  .ok
        CMPI r2, ' '
        BEQ  .ok
        CMPI r2, 9
        BNE  .bad
.ok:    RET
.bad:   BRA  bail

; skipblanks: advance r8 over spaces and tabs.
skipblanks:
        LDB  r2, [r8]
        CMPI r2, ' '
        BEQ  .skip
        CMPI r2, 9
        BNE  .ret
.skip:  INC  r8
        BRA  skipblanks
.ret:   RET

; atend: skip blanks; Z set if that is the end of the line.
atend:  BSR  skipblanks
        LDB  r2, [r8]
        RET

; noextra: bail unless only blanks are left.
noextra:
        BSR  atend
        BNE  .bad
        RET
.bad:   BRA  bail

; ---- the commands ----

cmd_w:  BSR  hexarg
        MOV  r9, r1             ; address
        BSR  hexarg             ; at least one value
.next:  ST   r1, [r9]           ; (word stores ignore address bit 0)
        ADDI r9, 2
        BSR  atend
        BEQ  .done
        BSR  hexarg
        BRA  .next
.done:  RET

cmd_b:  BSR  hexarg
        MOV  r9, r1
        BSR  hexarg
.next:  STB  r1, [r9]
        INC  r9
        BSR  atend
        BEQ  .done
        BSR  hexarg
        BRA  .next
.done:  RET

cmd_s:  BSR  hexarg
        LDB  r2, [r8]           ; exactly one blank, then the text
        BEQ  .done
        INC  r8
.copy:  LDB  r2, [r8]
        BEQ  .done
        STB  r2, [r1]
        INC  r1
        INC  r8
        BRA  .copy
.done:  RET

cmd_f:  BSR  hexarg
        MOV  r9, r1
        BSR  hexarg
        MOV  r10, r1
        BSR  hexarg
        BSR  noextra
        MOV  r2, r1
        MOV  r1, r9
        MOV  r3, r10
        JMP  memset             ; tail call

cmd_c:  BSR  hexarg
        MOV  r9, r1
        BSR  hexarg
        MOV  r10, r1
        BSR  hexarg
        BSR  noextra
        MOV  r3, r1
        MOV  r1, r10
        MOV  r2, r9
        JMP  memmove

cmd_r:  BSR  hexarg
        BSR  noextra
        MOV  r9, r1
        CALL print_hex16
        LI   r1, #s_eq
        CALL puts
        LD   r1, [r9]
        CALL print_hex16
        JMP  newline

cmd_d:  BSR  hexarg
        MOV  r9, r1             ; r9 = address
        BSR  hexarg
        MOV  r10, r1            ; r10 = bytes left
        BSR  noextra
.line:  TST  r10, r10
        BEQ  .done
        MVI  r11, 16            ; r11 = bytes on this line
        CMP  r10, r11
        BHS  .full
        MOV  r11, r10
.full:  MOV  r1, r9
        CALL print_hex16
        MVI  r1, ':'
        CALL putc
        PUSH r12
        PUSH r13
        MOV  r12, r9            ; r12 walks the line: there is no [reg + reg]
        MOV  r13, r9            ; r13 = end of this line's bytes
        ADD  r13, r11
        MVI  r1, 16
        SUB  r1, r11
        PUSH r1                 ; columns to pad on a short last line
.hex:   CALL space
        LDB  r1, [r12]
        CALL print_hex8
        INC  r12
        CMP  r12, r13
        BLO  .hex
        POP  r12                ; r12 = columns to pad (its own value is
        TST  r12, r12           ; still saved below on the stack)
        BEQ  .text0
.pad:   LI   r1, #s_pad         ; keep the text column lined up
        CALL puts
        DEC  r12
        BNE  .pad
.text0: CALL space
        CALL space
        MOV  r12, r9
.text:  LDB  r1, [r12]
        CMPI r1, ' '
        BLO  .dot
        CMPI r1, 0x7E
        BLS  .char
.dot:   MVI  r1, '.'
.char:  CALL putc
        INC  r12
        CMP  r12, r13
        BLO  .text
        POP  r13
        POP  r12
        CALL newline
        ADD  r9, r11
        SUB  r10, r11
        BRA  .line
.done:  RET

        .align 2
cmdtab: .byte 'w', 0
        .word cmd_w
        .byte 'b', 0
        .word cmd_b
        .byte 's', 0
        .word cmd_s
        .byte 'f', 0
        .word cmd_f
        .byte 'c', 0
        .word cmd_c
        .byte 'd', 0
        .word cmd_d
        .byte 'r', 0
        .word cmd_r
        .byte 0, 0
errsp:  .word 0
s_prompt: .asciz "> "
s_what: .asciz "?\n"
s_eq:   .asciz " = "
s_pad:  .asciz "   "
line:   .space LINESZ

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/string.s"
