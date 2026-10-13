; rpn: a signed 16-bit RPN calculator. Each input line is evaluated on its
; own: numbers are pushed, + - * / work on the top two. After each line the
; stack is printed bottom to top, or the first error.
;
; Numbers are decimal with an optional '-' (wrapping mod 2^16, like the
; arithmetic). Division rounds toward zero; -32768 / -1 wraps to -32768.

;! input-file: ../../v1_isa/programs/common/rpn.txt

        .include "lib/start.s"

LINESZ = 80
DEPTH  = 16

main:
.line:  LI   r1, #line
        MVI  r2, LINESZ
        CALL gets
        CMPI r1, -1
        BEQ  .eof
        LI   r1, #line          ; echo the line
        CALL puts
        LI   r1, #s_arrow
        CALL puts
        LI   r1, #line
        BSR  eval
        TST  r1, r1
        BNE  .error
        BSR  printstack
        BRA  .eol
.error: PUSH r1
        LI   r1, #s_error
        CALL puts
        POP  r1
        CALL puts
.eol:   CALL newline
        BRA  .line
.eof:   RET

; eval: r1 = line -> r1 = 0, or an error message. Leaves the stack in
; `stack` and its size in bytes in `depth`.
eval:   PUSH r8
        PUSH r9
        PUSH r10
        MOV  r8, r1             ; r8 = scan pointer
        MVI  r9, 0              ; r9 = stack size in bytes
.skip:  LDB  r1, [r8]           ; skip blanks
        BEQ  .end
        BSR  isblank
        BNE  .token
        INC  r8
        BRA  .skip
.token: MOV  r10, r8            ; r10 = end of the token
.tend:  INC  r10
        LDB  r1, [r10]
        BEQ  .tgot
        BSR  isblank
        BNE  .tend
.tgot:  LDB  r3, [r8]           ; a one-character token may be an operator
        MOV  r1, r10
        SUB  r1, r8
        CMPI r1, 1
        BNE  .number
        CMPI r3, '+'
        BEQ  .op
        CMPI r3, '-'
        BEQ  .op
        CMPI r3, '*'
        BEQ  .op
        CMPI r3, '/'
        BEQ  .op

.number:                        ; optional '-', then at least one digit
        MOV  r4, r8
        MVI  r5, 0              ; r5 = 1 if negative
        CMPI r3, '-'
        BNE  .digits
        MVI  r5, 1
        INC  r4
.digits:
        MVI  r6, 0              ; r6 = value
        CMP  r4, r10
        BEQ  .bad
.digit: LDB  r1, [r4]
        ADDI r1, -'0'
        CMPI r1, 9
        BHI  .bad               ; unsigned: catches below '0' too
        MOV  r7, r6             ; r6 = r6 * 10 + digit: no multiply,
        SHL  r6                 ; so (4x + x) * 2
        SHL  r6
        ADD  r6, r7
        SHL  r6
        ADD  r6, r1
        INC  r4
        CMP  r4, r10
        BNE  .digit
        TST  r5, r5
        BEQ  .push
        NEG  r6
.push:  CMPI r9, 2 * DEPTH
        BHS  .overflow
        ST   r6, [stack + r9]
        ADDI r9, 2
        MOV  r8, r10
        BRA  .skip

.op:    CMPI r9, 4
        BLO  .underflow
        ADDI r9, -4
        LD   r1, [stack + r9]   ; r1 = a (second from top), r2 = b (top)
        LD   r2, [stack + 2 + r9]
        CMPI r3, '+'
        BNE  .notadd
        ADD  r1, r2
        BRA  .result
.notadd:
        CMPI r3, '-'
        BNE  .notsub
        SUB  r1, r2
        BRA  .result
.notsub:
        CMPI r3, '*'
        BNE  .div
        CALL smul16             ; low half of the product
        BRA  .result
.div:   TST  r2, r2
        BEQ  .divzero
        CALL sdiv16
.result:
        ST   r1, [stack + r9]
        ADDI r9, 2
        MOV  r8, r10
        BRA  .skip

.end:   MVI  r1, 0
        BRA  .ret
.bad:   LI   r1, #s_bad
        BRA  .ret
.overflow:
        LI   r1, #s_overflow
        BRA  .ret
.underflow:
        LI   r1, #s_underflow
        BRA  .ret
.divzero:
        LI   r1, #s_divzero
.ret:   ST   r9, [depth]
        POP  r10
        POP  r9
        POP  r8
        RET

; isblank: Z set if r1 is a space or a tab.
isblank:
        CMPI r1, ' '
        BEQ  .ret
        CMPI r1, 9
.ret:   RET

; printstack: print the stack bottom to top, or "(empty)".
printstack:
        PUSH r8
        LD   r1, [depth]
        BNE  .some
        LI   r1, #s_empty
        CALL puts
        BRA  .done
.some:  MVI  r8, 0
.item:  LD   r1, [stack + r8]
        CALL print_s16
        ADDI r8, 2
        LD   r1, [depth]
        CMP  r8, r1
        BHS  .done
        CALL space
        BRA  .item
.done:  POP  r8
        RET

s_arrow:     .asciz " => "
s_error:     .asciz "error: "
s_bad:       .asciz "bad number"
s_overflow:  .asciz "stack overflow"
s_underflow: .asciz "stack underflow"
s_divzero:   .asciz "divide by zero"
s_empty:     .asciz "(empty)"
        .align 2
depth:  .word 0
stack:  .space 2 * DEPTH
line:   .space LINESZ

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/mul.s"
        .include "lib/div.s"
