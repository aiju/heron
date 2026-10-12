; rpn: a signed 16-bit RPN calculator (draft 1b). Each input line is
; evaluated on its own: numbers are pushed, + - * / work on the top two.
; After each line the stack is printed bottom to top, or the first error.
;
; Numbers are decimal with an optional '-' and wrap mod 2^16, like the
; arithmetic. Division rounds toward zero; -32768 / -1 wraps to -32768.
; The calculator stack holds 16-bit values sign-extended to 32 bits, so the
; 32-bit ADD, SUB, MULS and DIVS give the right 16-bit result after an SXH.

;! input: "3 4 +\n5 1 2 + 4 * + 3 -\n2 3 4 * +\n-7 2 /\n7 -2 /\n-7 -2 /\n100 7 / 100 7 * -\n1 2 3\n1 +\n9 -\n5 0 /\n5 5 5 - /\n32767 1 +\n-32768 -1 /\n300 300 *\n-300 300 *\n70000 1 +\n12 abc +\n4x 1\n--5\n-\n\t 42   -1  \n\n1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16\n1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17\n2 3 * 4 5 * + 6 /"

        .include "lib/start.s"

LINESZ = 80
DEPTH  = 16

main:   SAVE r8-r9
.line:  LEA  r1, [line]
        MOV  r2, #LINESZ
        BSR  gets
        CMP  r1, #-1
        BEQ  .eof
        LEA  r1, [line]         ; echo the line
        BSR  puts
        LEA  r1, [s_arrow]
        BSR  puts
        LEA  r1, [line]
        BSR  eval               ; -> r1 = 0 and r2 = stack end, or r1 = error
        TST  r1, r1
        BNE  .error
        LEA  r8, [stack]        ; r8 walks the stack bottom to top
        MOV  r9, r2             ; r9 = one past the top
        CMP  r8, r9
        BNE  .item
        LEA  r1, [s_empty]
        BSR  puts
        BRA  .eol
.item:  MOV  r1, [r8]+
        BSR  print_s32
        CMP  r8, r9
        BHS  .eol
        BSR  space
        BRA  .item
.error: MOV  r8, r1
        LEA  r1, [s_error]
        BSR  puts
        MOV  r1, r8
        BSR  puts
.eol:   BSR  newline
        BRA  .line
.eof:   RESTORE r8-r9
        RET

; eval: r1 = line -> r1 = 0 and r2 = one past the top of `stack`, or
; r1 = an error message. A leaf routine, so it works in r1-r7 only:
;   r4 = scan pointer, r5 = calculator stack pointer (the next free slot),
;   r1 = current character, r6 = number being parsed, r7 = its sign.
eval:   MOV  r4, r1
        LEA  r5, [stack]
.skip:  MOV  r1, byte [r4]+     ; skip blanks to the next token
        BEQ  .end
        CMP  r1, #' '
        BEQ  .skip
        CMP  r1, #9
        BEQ  .skip
        ; r1 = first character of a token, r4 points after it. A token of
        ; one character may be an operator.
        MOV  r2, byte [r4]
        BEQ  .single
        CMP  r2, #' '
        BEQ  .single
        CMP  r2, #9
        BNE  .number
.single:
        LEA  r3, [r1 - '*']     ; the operators are among '*' '+' ',' '-' '.' '/'
        CMP  r3, #'/' - '*'
        BHI  .number            ; unsigned: catches below '*' too
        LSL  r3, #2
        MOV  r3, [.optab + r3]  ; the handler, or 0 for ',' and '.'
        BEQ  .number
        CMP  r5, #stack + 8
        BLO  .underflow
        MOV  r2, -[r5]          ; r2 = b (top)
        MOV  r1, -[r5]          ; r1 = a (second from top)
        JMP  r3

.add:   ADD  r1, r2
        BRA  .result
.sub:   SUB  r1, r2
        BRA  .result
.mul:   MULS r1, r2             ; only the low half of the product matters
        BRA  .result
.div:   TST  r2, r2
        BEQ  .divzero
        DIVS r1, r2             ; -32768 / -1 = +32768 here, -32768 after SXH
.result:
        SXH  r1                 ; wrap to 16 bits
        ST   r1, [r5]+
        BRA  .skip

.number:                        ; optional '-', then at least one digit
        MOV  r7, #0
        CMP  r1, #'-'
        BNE  .first
        MOV  r7, #1
        MOV  r1, byte [r4]+     ; can't be a blank or NUL: "-" alone is an operator
.first: MOV  r6, #0
.digit: SUB  r1, #'0'
        CMP  r1, #9
        BHI  .bad               ; unsigned: catches below '0' too
        LEA  r6, [r6 + r6*4]    ; r6 * 5
        LEA  r6, [r1 + r6*2]    ; r6 * 10 + digit (wraps mod 2^32, so mod 2^16 too)
        MOV  r1, byte [r4]+
        BEQ  .nul
        CMP  r1, #' '
        BEQ  .push
        CMP  r1, #9
        BNE  .digit
.push:  TST  r7, r7
        BEQ  .pos
        NEG  r6
.pos:   SXH  r6
        CMP  r5, #stack + 4 * DEPTH
        BHS  .overflow
        ST   r6, [r5]+
        BRA  .skip
.nul:   DEC  r4                 ; end of the line: back onto the NUL for .skip
        BRA  .push

.end:   MOV  r1, #0
        MOV  r2, r5
        RET
.bad:   LEA  r1, [s_bad]
        RET
.overflow:
        LEA  r1, [s_overflow]
        RET
.underflow:
        LEA  r1, [s_underflow]
        RET
.divzero:
        LEA  r1, [s_divzero]
        RET

        .align 4
.optab: .word .mul, .add, 0, .sub, 0, .div     ; '*' '+' ',' '-' '.' '/'

s_arrow:     .asciz " => "
s_error:     .asciz "error: "
s_bad:       .asciz "bad number"
s_overflow:  .asciz "stack overflow"
s_underflow: .asciz "stack underflow"
s_divzero:   .asciz "divide by zero"
s_empty:     .asciz "(empty)"
        .align 4
stack:  .space 4 * DEPTH
line:   .space LINESZ

        .include "lib/console.s"
        .include "lib/print.s"
