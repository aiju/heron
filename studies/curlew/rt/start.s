; The Curlew runtime for draft 2: memory map, vectors, start-up, the
; output loop, errors and traps. implementation.md describes the design;
; codegen.py's docstring has the values and objects. The rules every
; routine keeps:
;
; - r13 is the heap's end less SLACK, r14 the heap pointer, sp the stack.
; - The collector's roots are the stack (every word that looks like a
;   pointer into the space being collected), the CAFs and rt_roots. A
;   routine that can collect saves only live values on the stack: a
;   register that isn't saved may hold a stale pointer, and must not be
;   saved where the collector would see it.
; - A thunk's code runs with its update frame on the stack: SAVE r6-r7,
;   the node and the return address. upd pops it.

; ---- memory map (the build sets CODE_BASE and HEAP_A ... STACK_LIMIT)
IO_CONS     = 0xFFFFFF00
FWD         = 3                 ; word 0 of an object the collector has moved
SLACK       = 1024              ; r13 = the heap's end - SLACK
K_THUNK     = 1
K_FUN       = 2
K_PAP       = 3
K_IND       = 4
K_CON       = 5

; ---- vectors: each jumps through a word
        .org 0x00
        JMP  [vec_reset]
        .org 0x04
        RTI                     ; IRQ (unused)
        .org 0x08
        JMP  [vec_illegal]
        .org 0x0C
        JMP  [vec_swi]
        .org 0x10
        JMP  [vec_div]
        .org 0x14
        JMP  [vec_addr]
        .org 0x18
        JMP  [vec_tag]
        .org 0x20
vec_reset:      .word boot
vec_illegal:    .word trap_illegal
vec_swi:        .word trap_illegal
vec_div:        .word trap_div
vec_addr:       .word trap_addr
vec_tag:        .word trap_tag

; ---- variables (in the first 32 KB: a 16-bit absolute address reaches them)
        .org 0x100
stack_limit:    .word STACK_LIMIT
cur_start:      .word 0         ; the half of the heap being allocated in
cur_end:        .word 0
other_start:    .word 0
other_end:      .word 0
gc_need:        .word 0         ; bytes the allocation that collected wants
; statistics, for the tools
gc_count:       .word 0
gc_copied:      .word 0         ; bytes copied by all collections
gc_alloc:       .word 0         ; bytes allocated before the current half was started
; the runtime's own roots
rt_roots:
input_obj:      .word input_entry + 1, 0    ; the console input, a thunk
rt_roots_end:

; ---- start-up
        .org CODE_BASE
rt_start:
boot:   MOV  sp, #STACK_TOP
        MOV  r1, #HEAP_A
        MOV  [cur_start], r1
        MOV  r14, r1
        MOV  r1, #HEAP_A + HEAP_SIZE
        MOV  [cur_end], r1
        MOV  r13, r1
        SUB  r13, #SLACK
        MOV  r1, #HEAP_B
        MOV  [other_start], r1
        MOV  r1, #HEAP_B + HEAP_SIZE
        MOV  [other_end], r1
.if onereg
        MOV  r11, #1            ; the mask a one-parcel TST uses
.endif
.if tagged
        BSR  trap_hash_init
.endif
        ; the output is main applied to the input
        MOV  r1, #input_obj + 1
        MOV  r6, #MAIN_ATOM
        CALL ap_1
        BSR  put_list
        HALT

; put_list: write the list of characters in r1 (evaluated) to the console.
put_list:
        MOV  -[sp], r7
.loop:  TST  r1, r1
        BEQ  .done              ; []
        MOV  r2, [r1 + 2]       ; the tail
        MOV  -[sp], r2
        MOV  r1, [r1 - 2]       ; the character
        TST  r1, #1
        BEQ  .put
        MOV  r6, r1
        CALL [r6 - 1]
.put:   LSR  r1, #2
        MOV  [IO_CONS], r1
        MOV  r1, [sp]+
        TST  r1, #1
        BEQ  .loop
        MOV  r6, r1
        CALL [r6 - 1]
        BRA  .loop
.done:  MOV  r7, [sp]+
        RET

; puts: write the bytes at r1 up to a zero.
puts:   MOVS r2, byte [r1]+
        BEQ  .done
        MOV  [IO_CONS], r2
        BRA  puts
.done:  RET

; ---- the thunk machinery

; upd: a thunk's code ends here with its value in r1: overwrite the
; thunk with an indirection to it, and return.
upd:    RESTORE r6-r7
        MOV  r12, #ind_entry + 1
        MOV  [r6 - 1], r12
        MOV  [r6 + 3], r1
        RET

        .align 4
        .word 0
        .word K_IND | 0 << 8 | 2 << 16
        .half 0
ind_entry:
        MOV  r1, [r6 + 3]
        RET

        .align 4
        .word 0
        .word K_PAP | 0 << 8 | 0 << 16
        .half 0
pap_entry:
        JMP  rt_internal        ; a partial application is never entered

; input_entry: the console input as a lazy list. Each thunk reads a
; character when it's evaluated: [] at the end, else the character and a
; new thunk for the rest.
        .align 4
        .word 0
        .word K_THUNK | 0 << 8 | 2 << 16
        .half 0
input_entry:
        SAVE r6-r7
        MOV  r1, [IO_CONS]
        CMP  r1, #-1
        BEQ  .eof
        LSL  r1, #2
.alloc: CMP  r14, r13
        BHI  .gc
        MOV  [r14], r1          ; a pair: the character,
        LEA  r2, [r14 + 9]
        MOV  [r14 + 4], r2      ; the rest, a new thunk
        MOV  r12, #input_entry + 1
        MOV  [r14 + 8], r12
        CLR  [r14 + 12]
        LEA  r1, [r14 + 2]
        ADD  r14, #16
        JMP  upd
.eof:   CLR  r1
        JMP  upd
.gc:    MOV  -[sp], r1
        MOV  r12, #16
        CALL rt_gc
        MOV  r1, [sp]+
        BRA  .alloc

; ---- errors

; rt_error: the program called error with the string in r1.
rt_error:
        MOV  -[sp], r1
        MOV  r1, #msg_error
        BSR  puts
        MOV  r1, [sp]+
        TST  r1, #1
        BEQ  .go
        MOV  r6, r1
        CALL [r6 - 1]
.go:    BSR  put_list
        MOV  r1, #msg_nl
        BSR  puts
        HALT

; an error with a message in the runtime: r1 = its bytes
rt_fail:
        MOV  -[sp], r1
        MOV  r1, #msg_error
        BSR  puts
        MOV  r1, [sp]+
        BSR  puts
        MOV  r1, #msg_nl
        BSR  puts
        HALT

rt_overflow:
        MOV  r1, #msg_overflow
        BRA  rt_fail
rt_stack:
        MOV  sp, #STACK_TOP - 64    ; room to print
        MOV  r1, #msg_stack
        BRA  rt_fail
rt_heap:
        MOV  r1, #msg_heap
        BRA  rt_fail
rt_nomatch:
        MOV  r1, #msg_nomatch
        BRA  rt_fail
rt_internal:
        MOV  r1, #msg_internal
        BRA  rt_fail
rt_toomany:
        MOV  r1, #msg_toomany
        BRA  rt_fail

; ---- traps (each pushed the PC and the flags)
trap_div:
        MOV  r1, #msg_div
        BRA  rt_fail
trap_illegal:
        MOV  r1, #msg_illegal
        BRA  rt_fail
trap_addr:
        MOV  r1, #msg_addr
        BRA  rt_fail

msg_error:      .byte 10, "error: ", 0
msg_nl:         .byte 10, 0
msg_overflow:   .byte "Int overflow", 0
msg_stack:      .byte "stack overflow", 0
msg_heap:       .byte "heap exhausted", 0
msg_nomatch:    .byte "internal: no alternative matched", 0
msg_internal:   .byte "internal: a partial application was entered", 0
msg_toomany:    .byte "internal: too many arguments", 0
msg_div:        .byte "divide by zero", 0
msg_illegal:    .byte "internal: illegal instruction", 0
msg_addr:       .byte "internal: address error", 0
        .align 2
