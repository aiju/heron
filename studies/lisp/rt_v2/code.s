; Support for compiled code: the primitives the compiler (compiler.lisp)
; uses to install code, and the routines compiled code calls. The build
; exports these routines' addresses to Lisp as the values of the symbols
; %rt:NAME (build.py, EXPORTS).

; ---- primitives for the compiler

; (%code-alloc n): n bytes of code space -> their address
p_codealloc:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, r6
        AND  r1, #1
        BNE  nn6
        MOV  r1, [code_free]
        MOV  r5, r6
        ASR  r5, #1
        ADD  r5, #3
        AND  r5, #-4
        ADD  r5, r1
        CMP  r5, #CCODE_END
        BHI  .full
        MOV  [code_free], r5
        ADD  r1, r1             ; as an integer
        RET
.full:  LEA  r1, [msg_codefull]
        BRA  fatal

; (%code-free): the next free address of code space
p_codefree:
        CMP  r2, #0
        BNE  err_argc
        MOV  r1, [code_free]
        ADD  r1, r1
        RET

; (%poke16 address value): store a parcel of code
p_poke16:
        CMP  r2, #2
        BNE  err_argc
        MOV  r1, r6
        OR   r1, r5
        AND  r1, #1
        BNE  .bad
        ASR  r6, #1
        ASR  r5, #1
        MOV  half [r6], r5
        MOV  r1, r13
        RET
.bad:   MOV  r1, r6
        AND  r1, #1
        BNE  nn6
        BRA  nn5

; (%make-closure code n): a compiled closure with n free variables, all nil
p_mkclosure:
        CMP  r2, #2
        BNE  err_argc
        MOV  r1, r6
        OR   r1, r5
        AND  r1, #1
        BNE  .bad
        MOV  r2, r5             ; 4 + 4 + 4n bytes, rounded
        ADD  r2, r5
        ADD  r2, #8 + 7
        AND  r2, #-8
        PUSH r7
        BSR  alloc
        POP  r7
        MOV  r4, r5             ; (1 + n) << 8 | B_CLO
        LSL  r4, #7
        ADD  r4, #1 << 8 | B_CLO
        MOV  [r1], r4
        ASR  r6, #1
        MOV  [r1 + 4], r6
        LEA  r3, [r1 + 8]
        MOV  r8, r5
.fill:  SUB  r8, #2
        BLO  .done
        MOV  [r3]+, r13
        BRA  .fill
.done:  OR   r1, #3
        RET
.bad:   MOV  r1, r6
        AND  r1, #1
        BNE  nn6
        BRA  nn5

; (%static-closure code): a compiled closure without free variables, in
; constant space (it never moves, so code can refer to it)
p_staticclo:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, r6
        AND  r1, #1
        BNE  nn6
        MOV  r2, #8
        PUSH r7
        BSR  const_alloc
        POP  r7
        MOV  r2, #1 << 8 | B_CLO
        MOV  [r1], r2
        ASR  r6, #1
        MOV  [r1 + 4], r6
        OR   r1, #3
        RET

; (%closure-set-code! c address): set a compiled closure's code
p_closetcode:
        CMP  r2, #2
        BNE  err_argc
        ASR  r5, #1
        MOV  [r6 + CALL_SLOT], r5
        MOV  r1, r6
        RET

; (%closure-set! c i v): set free variable i of a compiled closure
p_closet:
        CMP  r2, #3
        BNE  err_argc
        MOV  [r6 + r5*2 + 5], r4
        MOV  r1, r4
        RET

; (%address x): the word that is x, as an integer, if x is static (it
; never moves): a symbol in symbol space, nil, anything in constant space
; or the runtime's own objects. nil for anything in the heap.
p_address:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, r6
        CMP  r1, #HEAP_A
        BHS  .no
        ADD  r1, r1
        RET
.no:    MOV  r1, r13
        RET

; (%static-copy x): a copy of a quoted constant in constant space, which
; the collector never moves (and never scans: the copy must not point into
; the heap). nil if x holds anything that can't be copied.
p_staticcopy:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, r6
        PUSH r7
        BSR  static_copy
        POP  r7
        CMP  r1, #0
        BEQ  .no
        RET
.no:    MOV  r1, r13
        RET

; static_copy: r1 = a value -> r1 = its static copy, or 0.
static_copy:
        PUSH r7
        CMP  sp, [stack_limit]
        BLO  err_stack
        MOV  r2, r1
        AND  r2, #1
        BEQ  .same              ; an integer
        CMP  r1, #HEAP_A
        BLO  .same              ; already static
        MOV  r2, r1
        AND  r2, #3
        CMP  r2, #1
        BEQ  .pair
        MOV  r2, byte [r1 - 3]
        CMP  r2, #B_STR
        BEQ  .str
        CMP  r2, #B_VEC
        BEQ  .vec
        MOV  r1, #0             ; a heap symbol, a procedure: no
.same:  JMP  [sp]+
.pair:  PUSH r1                 ; the car, then the cdr, then a static pair
        MOV  r1, [r1 - 1]
        BSR  static_copy
        CMP  r1, #0
        BEQ  .fail1
        MOV  r2, [sp]
        MOV  [sp], r1
        MOV  r1, [r2 + 3]
        BSR  static_copy
        CMP  r1, #0
        BEQ  .fail1
        MOV  r6, r1
        MOV  r2, #8
        BSR  const_alloc
        POP  r2
        MOV  [r1], r2
        MOV  [r1 + 4], r6
        OR   r1, #1
        JMP  [sp]+
.fail1: ADD  sp, #4
        MOV  r1, #0
        JMP  [sp]+
.str:   MOV  r6, [r1 - 3]       ; copy the whole object
        LSR  r6, #8
        ADD  r6, #8 + 7
        AND  r6, #-8
        BRA  .copy
.vec:   PUSH r1                 ; the elements first, in place in a new vector
        MOV  r2, [r1 - 3]
        LSR  r2, #8
        LSL  r2, #2
        ADD  r2, #4 + 7
        AND  r2, #-8
        BSR  const_alloc
        MOV  r2, [sp]
        MOV  r6, [r2 - 3]
        MOV  [r1], r6
        LEA  r6, [not_proc]
        MOV  [r1 + 4], r6
        OR   r1, #3
        PUSH r1                 ; [sp] the copy, [sp + 4] the original
        MOV  r5, #0
.elt:   MOV  r2, [sp + 4]
        MOV  r6, [r2 - 3]
        LSR  r6, #8
        SUB  r6, #1             ; the elements: the size less the call slot
        LSL  r6, #2
        CMP  r5, r6
        BHS  .vdone
        PUSH r5
        MOV  r1, [r2 + r5 + VEC_ELTS]
        BSR  static_copy
        POP  r5
        CMP  r1, #0
        BEQ  .vfail
        MOV  r2, [sp]
        MOV  [r2 + r5 + VEC_ELTS], r1
        ADD  r5, #4
        BRA  .elt
.vdone: POP  r1
        ADD  sp, #4
        JMP  [sp]+
.vfail: ADD  sp, #8
        MOV  r1, #0
        JMP  [sp]+
.copy:  ; r1 = the object, r6 = its size: a byte-for-byte copy
        PUSH r1
        MOV  r2, r6
        BSR  const_alloc
        POP  r9
        SUB  r9, #3
        MOV  r10, r1
        MOV  r11, r6
.cw:    MOV  r12, [r9]+
        MOV  [r10]+, r12
        SUB  r11, #4
        BNE  .cw
        OR   r1, #3
        JMP  [sp]+

; const_alloc: r2 = bytes (a multiple of 8) -> r1 = their address in
; constant space. Keeps r2-r12.
const_alloc:
        MOV  r1, [const_free]
        PUSH r2
        ADD  r2, r1
        CMP  r2, #CONST_END
        BHI  .full
        MOV  [const_free], r2
        POP  r2
        RET
.full:  LEA  r1, [msg_constfull]
        BRA  fatal

; (%macro sym): the symbol's macro expander, or nil
p_macro:
        CMP  r2, #1
        BNE  err_argc
        MOV  r9, r6
        PUSH r7
        BSR  is_sym
        POP  r7
        BNE  ns6
        MOV  r1, [r6 + SYM_SPECIAL]
        AND  r1, #-4
        CMP  r1, #SF_MACRO
        BNE  ret_nil
        MOV  r1, [r6 + SYM_MACRO]
        RET

; (%special? sym): t if the symbol names a special form (not a macro)
p_specialp:
        CMP  r2, #1
        BNE  err_argc
        MOV  r9, r6
        PUSH r7
        BSR  is_sym
        POP  r7
        BNE  ret_nil
        MOV  r1, [r6 + SYM_SPECIAL]
        AND  r1, #-4
        BEQ  ret_nil
        CMP  r1, #SF_MACRO
        BEQ  ret_nil
        BRA  ret_t

; (%set-macro! sym f): make sym a macro with expander f
p_setmacro:
        CMP  r2, #2
        BNE  err_argc
        MOV  r9, r6
        PUSH r7
        BSR  is_sym
        POP  r7
        BNE  ns6
        MOV  [r6 + SYM_MACRO], r5
        MOV  r1, [r6 + SYM_SPECIAL]
        AND  r1, #LOCAL
        OR   r1, #SF_MACRO
        MOV  [r6 + SYM_SPECIAL], r1
        MOV  r1, r6
        RET

; (%poke8 address value): store a byte (the compiler's category map)
p_poke8:
        CMP  r2, #2
        BNE  err_argc
        MOV  r1, r6
        OR   r1, r5
        AND  r1, #1
        BNE  .bad
        ASR  r6, #1
        ASR  r5, #1
        MOV  byte [r6], r5
        MOV  r1, r13
        RET
.bad:   MOV  r1, r6
        AND  r1, #1
        BNE  nn6
        BRA  nn5

; (%run-begin), (%run-end): mark when compiled code starts and stops
; running, in mark_log: the cycle counter (as the simulator's reference
; configuration counts it), with bit 0 set at a start. For the tools.
p_runbegin:
        CMP  r2, #0
        BNE  err_argc
        MOV  r1, #1
        MOV  [running], r1
        MOV  r1, [IO_CYC]
        OR   r1, #1
        PUSH r7
        BSR  mark
        POP  r7
        BRA  ret_nil

p_runend:
        CMP  r2, #0
        BNE  err_argc
        PUSH r7
        BSR  run_end
        POP  r7
        BRA  ret_nil

run_end:
        CLR  [running]
        MOV  r1, [IO_CYC]
        AND  r1, #-2
mark:   MOV  r2, [marks]
        CMP  r2, #MARKS_MAX
        BHS  .full
        LEA  r6, [mark_log]
        MOV  [r6 + r2], r1
        ADD  r2, #4
        MOV  [marks], r2
.full:  RET

MARKS_MAX = 4096
        .align 4
mark_log:
        .space MARKS_MAX

; (%reload-prelude): read the prelude again, then go on with the console
; (once the compiler is loaded: it compiles the prelude)
p_reload:
        CMP  r2, #0
        BNE  err_argc
        LEA  r1, [prelude_text]
        MOV  [in_ptr], r1
        MOV  r1, #2
        MOV  [in_phase], r1
        BRA  ret_nil

; (%save-image): stop the machine so the tools can take a copy of memory
; to start later runs from (machine.py, core)
p_saveimage:
        CMP  r2, #0
        BNE  err_argc
        MOV  [saved_hp], r14
        MOV  r1, #1
        MOV  [resume], r1
        HALT
        BRA  ret_nil

; ---- routines compiled code calls

; rt_num2: r1, r3 are the operands of a compiled arithmetic operation, and
; one isn't a number: report the first that isn't.
rt_num2:
        MOV  r9, r1
        AND  r9, #1
        BNE  err_notnum
        MOV  r1, r3
        BRA  err_notnum

; rt_rest: the list of a call's arguments after the first r9 (r9 <= 5):
; r2 = their number, r6, r5, r4, r3, r8, r0 = the arguments -> r12 (to be
; moved to where it belongs at once: r12 isn't a root). Keeps r0-r6, r8 (r7 is the
; return address: the caller has kept its own).
rt_rest:
        PUSH r7
        PUSH r1                 ; (the caller's closure)
        MOV  r12, r13
        MOV  r10, r2            ; the last argument in a register
        CMP  r2, #6
        BLS  .loop
        MOV  r12, r0            ; arguments 6..n are a list already
        MOV  r10, #5
.loop:  CMP  r10, r9
        BLS  .done
        CMP  r10, #6
        BEQ  .a6
        CMP  r10, #5
        BEQ  .a5
        CMP  r10, #4
        BEQ  .a4
        CMP  r10, #3
        BEQ  .a3
        CMP  r10, #2
        BEQ  .a2
        MOV  r11, r6
        BRA  .c
.a6:    MOV  r11, r0
        BRA  .c
.a5:    MOV  r11, r8
        BRA  .c
.a4:    MOV  r11, r3
        BRA  .c
.a3:    MOV  r11, r4
        BRA  .c
.a2:    MOV  r11, r5
.c:     BSR  cons_r
        MOV  r12, r1
        DEC  r10
        BRA  .loop
.done:  POP  r1
        JMP  [sp]+

msg_codefull:   .asciz "code space full"
msg_constfull:  .asciz "constant space full"
        .align 2
