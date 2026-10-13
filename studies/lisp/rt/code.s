; Support for compiled code: the primitives the compiler (compiler.lisp)
; uses to install code, and the routines compiled code calls. The build
; exports these routines' addresses to Lisp as the values of the symbols
; %rt:NAME (build.py, EXPORTS).

; ---- primitives for the compiler

; (%code-alloc n): n bytes of code space -> their address
p_codealloc:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, r3
        AND  r1, #1
        BNE  nn3
        MOV  r1, [code_free]
        MOV  r4, r3
        ASR  r4, #1
        ADD  r4, #3
        AND  r4, #-4
        ADD  r4, r1
        CMP  r4, #CCODE_END
        BHI  .full
        ST   r4, [code_free]
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
        MOV  r1, r3
        OR   r1, r4
        AND  r1, #1
        BNE  .bad
        ASR  r3, #1
        ASR  r4, #1
        ST   r4, half [r3]
        MOV  r1, r13
        RET
.bad:   MOV  r1, r3
        AND  r1, #1
        BNE  nn3
        BRA  nn4

; (%make-closure code n): a compiled closure with n free variables, all nil
p_mkclosure:
        CMP  r2, #2
        BNE  err_argc
        MOV  r1, r3
        OR   r1, r4
        AND  r1, #1
        BNE  .bad
        MOV  r2, r4             ; 4 + 4 + 4n bytes, rounded
        ADD  r2, r4
        ADD  r2, #8 + 7
        AND  r2, #-8
        BSR  alloc
        MOV  r5, r4             ; (1 + n) << 8 | B_CLO
        LSL  r5, #7
        ADD  r5, #1 << 8 | B_CLO
        ST   r5, [r1]
        ASR  r3, #1
        ST   r3, [r1 + 4]
        LEA  r6, [r1 + 8]
        MOV  r7, r4
.fill:  SUB  r7, #2
        BLO  .done
        ST   r13, [r6]+
        BRA  .fill
.done:  OR   r1, #3
        RET
.bad:   MOV  r1, r3
        AND  r1, #1
        BNE  nn3
        BRA  nn4

; (%static-closure code): a compiled closure without free variables, in
; constant space (it never moves, so code can refer to it)
p_staticclo:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, r3
        AND  r1, #1
        BNE  nn3
        MOV  r2, #8
        BSR  const_alloc
        MOV  r2, #1 << 8 | B_CLO
        ST   r2, [r1]
        ASR  r3, #1
        ST   r3, [r1 + 4]
        OR   r1, #3
        RET

; (%closure-set! c i v): set free variable i of a compiled closure
p_closet:
        CMP  r2, #3
        BNE  err_argc
        ST   r5, [r3 + r4*2 + 5]
        MOV  r1, r5
        RET

; (%address x): the word that is x, as an integer, if x is static (it
; never moves): a symbol in symbol space, nil, anything in constant space
; or the runtime's own objects. nil for anything in the heap.
p_address:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, r3
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
        MOV  r1, r3
        BSR  static_copy
        CMP  r1, #0
        BEQ  .no
        RET
.no:    MOV  r1, r13
        RET

; static_copy: r1 = a value -> r1 = its static copy, or 0.
static_copy:
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
.same:  RET
.pair:  PUSH r1                 ; the car, then the cdr, then a static pair
        MOV  r1, [r1 - 1]
        BSR  static_copy
        CMP  r1, #0
        BEQ  .fail1
        MOV  r2, [sp]
        ST   r1, [sp]
        MOV  r1, [r2 + 3]
        BSR  static_copy
        CMP  r1, #0
        BEQ  .fail1
        MOV  r3, r1
        MOV  r2, #8
        BSR  const_alloc
        POP  r2
        ST   r2, [r1]
        ST   r3, [r1 + 4]
        OR   r1, #1
        RET
.fail1: ADD  sp, #4
        MOV  r1, #0
        RET
.str:   MOV  r3, [r1 - 3]       ; copy the whole object
        LSR  r3, #8
        ADD  r3, #8 + 7
        AND  r3, #-8
        BRA  .copy
.vec:   PUSH r1                 ; the elements first, in place in a new vector
        MOV  r2, [r1 - 3]
        LSR  r2, #8
        LSL  r2, #2
        ADD  r2, #4 + 7
        AND  r2, #-8
        BSR  const_alloc
        MOV  r2, [sp]
        MOV  r3, [r2 - 3]
        ST   r3, [r1]
        LEA  r3, [not_proc]
        ST   r3, [r1 + 4]
        OR   r1, #3
        PUSH r1                 ; [sp] the copy, [sp + 4] the original
        MOV  r4, #0
.elt:   MOV  r2, [sp + 4]
        MOV  r3, [r2 - 3]
        LSR  r3, #8
        SUB  r3, #1             ; the elements: the size less the call slot
        LSL  r3, #2
        CMP  r4, r3
        BHS  .vdone
        PUSH r4
        MOV  r1, [r2 + r4 + VEC_ELTS]
        BSR  static_copy
        POP  r4
        CMP  r1, #0
        BEQ  .vfail
        MOV  r2, [sp]
        ST   r1, [r2 + r4 + VEC_ELTS]
        ADD  r4, #4
        BRA  .elt
.vdone: POP  r1
        ADD  sp, #4
        RET
.vfail: ADD  sp, #8
        MOV  r1, #0
        RET
.copy:  ; r1 = the object, r3 = its size: a byte-for-byte copy
        PUSH r1
        MOV  r2, r3
        BSR  const_alloc
        POP  r9
        SUB  r9, #3
        MOV  r10, r1
        MOV  r11, r3
.cw:    MOV  r12, [r9]+
        ST   r12, [r10]+
        SUB  r11, #4
        BNE  .cw
        OR   r1, #3
        RET

; const_alloc: r2 = bytes (a multiple of 8) -> r1 = their address in
; constant space. Keeps r2-r12.
const_alloc:
        MOV  r1, [const_free]
        PUSH r2
        ADD  r2, r1
        CMP  r2, #CONST_END
        BHI  .full
        ST   r2, [const_free]
        POP  r2
        RET
.full:  LEA  r1, [msg_constfull]
        BRA  fatal

; (%macro sym): the symbol's macro expander, or nil
p_macro:
        CMP  r2, #1
        BNE  err_argc
        MOV  r9, r3
        BSR  is_sym
        BNE  ns3
        MOV  r1, [r3 + SYM_SPECIAL]
        AND  r1, #-4
        CMP  r1, #SF_MACRO
        BNE  ret_nil
        MOV  r1, [r3 + SYM_MACRO]
        RET

; (%special? sym): t if the symbol names a special form (not a macro)
p_specialp:
        CMP  r2, #1
        BNE  err_argc
        MOV  r9, r3
        BSR  is_sym
        BNE  ret_nil
        MOV  r1, [r3 + SYM_SPECIAL]
        AND  r1, #-4
        BEQ  ret_nil
        CMP  r1, #SF_MACRO
        BEQ  ret_nil
        BRA  ret_t

; (%set-macro! sym f): make sym a macro with expander f
p_setmacro:
        CMP  r2, #2
        BNE  err_argc
        MOV  r9, r3
        BSR  is_sym
        BNE  ns3
        ST   r4, [r3 + SYM_MACRO]
        MOV  r1, [r3 + SYM_SPECIAL]
        AND  r1, #LOCAL
        OR   r1, #SF_MACRO
        ST   r1, [r3 + SYM_SPECIAL]
        MOV  r1, r3
        RET

; ---- routines compiled code calls

; rt_num2: r1, r3 are the operands of an arithmetic operation, and one
; isn't a number: report the first that isn't.
rt_num2:
        MOV  r9, r1
        AND  r9, #1
        BNE  err_notnum
        MOV  r1, r3
        BRA  err_notnum

; rt_rest: the list of a call's arguments after the first r9 (r9 <= 5):
; r2 = their number, r3-r8 = the arguments -> r12 (to be moved to where it
; belongs at once: r12 isn't a root). Keeps r1-r8.
rt_rest:
        PUSH r1                 ; (the caller's closure)
        MOV  r12, r13
        MOV  r10, r2            ; the last argument in a register
        CMP  r2, #6
        BLS  .loop
        MOV  r12, r8            ; arguments 6..n are a list already
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
        MOV  r11, r3
        BRA  .c
.a6:    MOV  r11, r8
        BRA  .c
.a5:    MOV  r11, r7
        BRA  .c
.a4:    MOV  r11, r6
        BRA  .c
.a3:    MOV  r11, r5
        BRA  .c
.a2:    MOV  r11, r4
.c:     BSR  cons_r
        MOV  r12, r1
        DEC  r10
        BRA  .loop
.done:  POP  r1
        RET

msg_codefull:   .asciz "code space full"
msg_constfull:  .asciz "constant space full"
        .align 2
