; vm: a bytecode interpreter for a small stack machine with 32-bit signed
; values (the VM_SOURCE comment block in programs/reference.py is the spec),
; running the program in ../common/vm_code.s: sums of squares, primes by
; trial division, recursive fib(16), Collatz chains and signed division.
;
; Design:
; - r8 points at the current instruction's opcode. Each handler ends with
;   its own copy of the dispatch, which reads the next opcode at [r8 + n]
;   (n = this instruction's length, so operand bytes are short-form loads at
;   [r8 + 1]...), steps r8 and jumps through optable:
;
;       LDB  r1, [r8 + n]
;       ADDI r8, n
;       LSL  r1, #2
;       LD   r1, [optable + r1]
;       JMP  r1
;
; - The data stack is the machine stack: the top of stack is cached in r9,
;   the rest is at [sp], [sp + 4], ... so PUSH/POP are one instruction each.
;   (On entry r9 holds a dummy value that the first push puts underneath.)
; - The return stack is a separate array, r10 its next free slot; it holds
;   absolute addresses.
; - Globals are 16 words at globals.

        .include "lib/start.s"

main:   SAVE r8-r14
        MOV  r14, sp            ; to drop whatever the VM leaves on the stack
        LEA  r8, vm_code
        LEA  r10, rstack
        MVI  r9, 0
        LDB  r1, [r8]           ; dispatch the first instruction
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_halt:
        MOV  sp, r14
        RESTORE r8-r14
        RET

op_push:                        ; PUSH i32 (little-endian, unaligned)
        PUSH r9
        LDB  r9, [r8 + 4]
        LDB  r1, [r8 + 3]
        LSL  r9, #8
        OR   r9, r1
        LDB  r1, [r8 + 2]
        LSL  r9, #8
        OR   r9, r1
        LDB  r1, [r8 + 1]
        LSL  r9, #8
        OR   r9, r1
        LDB  r1, [r8 + 5]
        ADDI r8, 5
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_pushb:                       ; PUSHB i8 (sign-extended)
        PUSH r9
        LDSB r9, [r8 + 1]
        LDB  r1, [r8 + 2]
        ADDI r8, 2
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_load:                        ; LOAD g
        PUSH r9
        LDB  r1, [r8 + 1]
        LSL  r1, #2
        LD   r9, [globals + r1]
        LDB  r1, [r8 + 2]
        ADDI r8, 2
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_store:                       ; STORE g
        LDB  r1, [r8 + 1]
        LSL  r1, #2
        ST   r9, [globals + r1]
        POP  r9
        LDB  r1, [r8 + 2]
        ADDI r8, 2
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_add: POP  r1                 ; a b -> a + b
        ADD  r9, r1
        LDB  r1, [r8 + 1]
        ADDI r8, 1
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_sub: POP  r1                 ; a b -> a - b
        SUB  r1, r9
        MOV  r9, r1
        LDB  r1, [r8 + 1]
        ADDI r8, 1
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_mul: POP  r1                 ; a b -> a * b (b is the multiplier: the
        MULS r1, r9             ; loop stops at b's top bit, and b is the
        MOV  r9, r1             ; small one in n * 3)
        LDB  r1, [r8 + 1]
        ADDI r8, 1
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_div: POP  r1                 ; a b -> a / b, rounding toward zero
        DIVS r1, r9
        MOV  r9, r1
        LDB  r1, [r8 + 1]
        ADDI r8, 1
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_mod: POP  r1                 ; a b -> a mod b, with the sign of a
        DIVS r1, r9
        MFHI r9
        LDB  r1, [r8 + 1]
        ADDI r8, 1
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_lt:  POP  r1                 ; a b -> a < b (signed)
        CMP  r1, r9
        SETLT r9
        LDB  r1, [r8 + 1]
        ADDI r8, 1
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_eq:  POP  r1                 ; a b -> a == b
        CMP  r1, r9
        SETEQ r9
        LDB  r1, [r8 + 1]
        ADDI r8, 1
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_jz:  TST  r9, r9             ; JZ a16: pop, jump if zero
        POP  r9                 ; (POP is RESTORE: the flags survive)
        BEQ  jump
        LDB  r1, [r8 + 3]
        ADDI r8, 3
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_jnz: TST  r9, r9             ; JNZ a16: pop, jump if not zero
        POP  r9
        BNE  jump
        LDB  r1, [r8 + 3]
        ADDI r8, 3
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_call:                        ; CALL a16: return address to the return stack
        LEA  r1, [r8 + 3]
        ST   r1, [r10]
        ADDI r10, 4
op_jmp:                         ; JMP a16 (an unaligned little-endian offset)
jump:   LDB  r1, [r8 + 2]
        LDB  r2, [r8 + 1]
        LSL  r1, #8
        OR   r1, r2
        LEA  r8, [vm_code + r1]
        LDB  r1, [r8]
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_ret: ADDI r10, -4            ; RET
        LD   r8, [r10]
        LDB  r1, [r8]
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_dup: PUSH r9                 ; a -> a a
        LDB  r1, [r8 + 1]
        ADDI r8, 1
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_drop:                        ; a ->
        POP  r9
        LDB  r1, [r8 + 1]
        ADDI r8, 1
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_swap:                        ; a b -> b a
        LD   r1, [sp]
        ST   r9, [sp]
        MOV  r9, r1
        LDB  r1, [r8 + 1]
        ADDI r8, 1
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_over:                        ; a b -> a b a
        PUSH r9
        LD   r9, [sp + 4]
        LDB  r1, [r8 + 1]
        ADDI r8, 1
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

op_print:                       ; a -> (prints a and a newline)
        MOV  r1, r9
        POP  r9
        BSR  print_s32
        BSR  newline
        LDB  r1, [r8 + 1]
        ADDI r8, 1
        LSL  r1, #2
        LD   r1, [optable + r1]
        JMP  r1

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

        .include "../common/vm_code.s"
