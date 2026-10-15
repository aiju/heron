; vm: a bytecode interpreter for a small stack machine with 32-bit signed
; values (the VM_SOURCE comment block in studies/v1_isa/programs/reference.py
; is the spec), running the program in studies/v1_isa/programs/common/
; vm_code.s: sums of squares, primes by trial division, recursive fib(16),
; Collatz chains and signed division.
;
; Design:
; - r8 points just past the opcode being executed, so operand bytes are
;   read with byte [r8]+. Each handler ends with its own copy of the
;   two-instruction dispatch:
;
;       MOV  r1, byte [r8]+     ; next opcode
;       JMP  [r13 + r1*4]       ; r13 = optable
;
; - The data stack is the machine stack: the top of stack is cached in r9,
;   the rest is at [sp], [sp + 4], ..., so a binary operator can take its
;   left operand straight from the stack: ADD r9, [sp]+.
;   (On entry r9 holds a dummy value that the first push puts underneath.)
; - The return stack is a separate array, r10 its next free slot; it holds
;   absolute addresses.
; - r11 = globals (16 words).

        .include "lib/start.s"

main:   SAVE r8-r14
        MOV  r14, sp            ; to drop whatever the VM leaves on the stack
        MOV  r8, #vm_code
        MOV  r10, #rstack
        MOV  r11, #globals
        MOV  r13, #optable
        MOV  r9, #0
        MOV  r1, byte [r8]+     ; dispatch the first instruction
        JMP  [r13 + r1*4]

op_halt:
        MOV  sp, r14
        RESTORE r8-r14
        RET

op_push:                        ; PUSH i32 (little-endian, unaligned)
        MOV  -[sp], r9
        MOV  r9, byte [r8 + 3]
        LSL  r9, #8
        OR   r9, byte [r8 + 2]
        LSL  r9, #8
        OR   r9, byte [r8 + 1]
        LSL  r9, #8
        OR   r9, byte [r8]
        ADD  r8, #4
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_pushb:                       ; PUSHB i8 (sign-extended)
        MOV  -[sp], r9
        MOV  r9, byte [r8]+
        SXB  r9
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_load:                        ; LOAD g
        MOV  -[sp], r9
        MOV  r1, byte [r8]+
        MOV  r9, [r11 + r1*4]
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_store:                       ; STORE g
        MOV  r1, byte [r8]+
        MOV  [r11 + r1*4], r9
        MOV  r9, [sp]+
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_add: ADD  r9, [sp]+          ; a b -> a + b
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_sub: NEG  r9                 ; a b -> a - b = -b + a
        ADD  r9, [sp]+
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_mul: MOV  r1, [sp]+          ; a b -> a * b (b is the multiplier: the
        MULS r1, r9             ; loop stops at b's top bit, and b is the
        MOV  r9, r1             ; small one in n * 3)
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_div: MOV  r1, [sp]+          ; a b -> a / b, rounding toward zero
        DIVS r1, r9
        MOV  r9, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_mod: MOV  r1, [sp]+          ; a b -> a mod b, with the sign of a
        DIVS r1, r9
        MFSR r9, hi
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_lt:  CMP  r9, [sp]+          ; a b -> a < b (signed): flags of b - a,
        SETGT r9                ; so a < b is GT
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_eq:  CMP  r9, [sp]+          ; a b -> a == b
        SETEQ r9
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

; JZ/JNZ pop the condition: the test branches first and each path pops for
; itself.
op_jz:  TST  r9, r9             ; JZ a16: jump if zero
        BEQ  .take
        MOV  r9, [sp]+
        ADD  r8, #2
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]
.take:  MOV  r9, [sp]+
        BRA  jump

op_jnz: TST  r9, r9             ; JNZ a16: jump if not zero
        BNE  .take
        MOV  r9, [sp]+
        ADD  r8, #2
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]
.take:  MOV  r9, [sp]+
        BRA  jump

op_call:                        ; CALL a16: return address to the return stack
        LEA  r1, [r8 + 2]
        MOV  [r10]+, r1
op_jmp:                         ; JMP a16 (an unaligned little-endian offset)
jump:   MOV  r1, byte [r8 + 1]
        LSL  r1, #8
        OR   r1, byte [r8]
        LEA  r8, [vm_code + r1]
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_ret: MOV  r8, -[r10]         ; RET
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_dup: MOV  -[sp], r9          ; a -> a a
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_drop:                        ; a ->
        MOV  r9, [sp]+
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_swap:                        ; a b -> b a
        MOV  r1, [sp]
        MOV  [sp], r9
        MOV  r9, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_over:                        ; a b -> a b a
        MOV  -[sp], r9
        MOV  r9, [sp + 4]
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_print:                       ; a -> (prints a and a newline)
        MOV  r1, r9
        MOV  r9, [sp]+
        BSR  print_s32
        BSR  newline
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

        .include "lib/console.s"
        .include "lib/print.s"

; ---- data ----

        .align 4
optable:
        .word op_halt, op_push, op_pushb, op_load, op_store, op_add    ; 00-05
        .word op_sub, op_mul, op_div, op_mod, op_lt, op_eq             ; 06-0B
        .word op_jz, op_jmp, op_jnz, op_dup, op_drop, op_swap          ; 0C-11
        .word op_over, op_call, op_ret, op_print                       ; 12-15

globals:
        .space 4 * 16
rstack: .space 4 * 32

        .include "../../v1_isa/programs/common/vm_code.s"
