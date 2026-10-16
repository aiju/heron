; The interpreter: eval, apply and the special forms.
;
; An environment is nil (the global scope) or a frame: an object holding
; its parent and (name, value) pairs. An interpreted closure (T_FUN) holds
; its parameters, body and environment, and the shape of its parameter list:
; 4 * the number of required parameters, + 2 if there's a rest parameter.
;
; A symbol's special field is 4 * its special form's index (sf_handlers),
; plus 2 once it has been a local variable's name anywhere. A symbol
; without that bit can only have a global value, so looking it up skips
; the frames.
;
; Calling a procedure ("the calling convention", shared with primitives
; and compiled code): r1 = the procedure, r2 = the number of arguments,
; r3-r8 = arguments 1-6; with more than 6, r3-r7 hold 1-5 and r8 a list of
; the rest. The call jumps to the procedure's call slot, [r1 + 1]. The
; result comes back in r1; r1-r12 are not preserved.

LOCAL   = 2                     ; the "has been a local" bit of the special field

; eval: r1 = an expression, r2 = an environment -> r1 = its value.
eval:   CMP  sp, [stack_limit]
        BLO  err_stack
eval_t:                         ; for tail calls: the stack hasn't grown
        MOV  r3, r1
        AND  r3, #3
        CMP  r3, #1
        BEQ  ev_pair
        CMP  r3, #3
        BNE  .self              ; a number
        MOV  r3, byte [r1 - 3]
        CMP  r3, #B_SYM
        BEQ  ev_var
.self:  RET

; ev_var: r1 = a symbol, r2 = an environment -> r1 = its value. Uses r2,
; r4, r5.
ev_var: MOV  r4, [r1 + SYM_SPECIAL]
        AND  r4, #LOCAL
        BEQ  .global
        CMP  r2, r13
        BEQ  .global
.frame: MOV  r4, [r2 - 3]       ; (1 + 2k) << 8 | ...
        LSR  r4, #6
        AND  r4, #-4            ; 4 + 8k
        LEA  r4, [r2 + r4 + 1]  ; the end of the frame
        LEA  r5, [r2 + 5]       ; the first name
.slot:  CMP  r5, r4
        BHS  .up
        CMP  r1, [r5]+
        BEQ  .found
        ADD  r5, #4
        BRA  .slot
.found: MOV  r1, [r5]
        RET
.up:    MOV  r2, [r2 + 1]       ; the parent
        CMP  r2, r13
        BNE  .frame
.global:
        MOV  r2, [r1 + SYM_VALUE]
        CMP  r2, #UNB
        BEQ  err_unbound
        MOV  r1, r2
        RET

; ev_pair: r1 = a form (a pair), r2 = an environment.
ev_pair:
        MOV  r3, [r1 - 1]       ; the operator
        MOV  r4, r3
        AND  r4, #3
        CMP  r4, #3
        BNE  ev_app
        MOV  r4, byte [r3 - 3]
        CMP  r4, #B_SYM
        BNE  ev_app
        MOV  r4, [r3 + SYM_SPECIAL]
        AND  r4, #-4
        BEQ  ev_app
        JMP  [sf_handlers + r4] ; r1 = the form, r2 = the environment, r3 = its symbol

; ev_app: a call. r1 = the form, r2 = the environment, r3 = the operator.
; The arguments must be a proper list, checked before anything is
; evaluated.
ev_app: MOV  r5, [r1 + 3]       ; the argument expressions
        MOV  r6, r5
        MOV  r4, #0
.cnt:   CMP  r6, r13
        BEQ  .cntd
        MOV  r7, r6
        AND  r7, #3
        CMP  r7, #1
        BNE  err_syntax
        ADD  r4, #4
        MOV  r6, [r6 + 3]
        BRA  .cnt
.cntd:  PUSH r2
        PUSH r5
        PUSH r4                 ; 4n
        MOV  r1, r3
        BSR  eval_one           ; the procedure
        POP  r4
        POP  r5
        POP  r2
        PUSH r1
        MOV  r6, r4             ; a zero slot per argument
.zero:  SUB  r6, #4
        BLO  .zd
        ST   r0, -[sp]
        BRA  .zero
.zd:    PUSH r4
        MOV  r1, r5
        LEA  r3, [sp + 4]
        MOV  r4, #0
        BSR  eval_into
        POP  r2
        ; fall through

; apply_stack: apply [sp + 4n] to the n arguments at [sp], [sp + 4], ...;
; r2 = 4n. They're taken off the stack. Jumped to, not called: the
; procedure returns to whoever is below them on the stack.
apply_stack:
        MOV  r1, [sp + r2]      ; the procedure
        MOV  r9, [r1 + CALL_SLOT]   ; its code (and the type check)
        CMP  r9, #interp_entry
        BEQ  apply_fun
        CMP  r2, #24
        BHI  .many
        JMP  [ap_tab + r2]
.many:  MOV  r10, r2            ; arguments 6..n go in a list
        MOV  r11, r2
        MOV  r4, r13
.mk:    SUB  r11, #4
        CMP  r11, #20
        BLO  .mkd
        MOV  r3, [sp + r11]
        BSR  cons
        MOV  r4, r1
        BRA  .mk
.mkd:   MOV  r8, r4
        MOV  r1, [sp + r10]     ; (it may have moved)
        MOV  r2, r10
        LSR  r2, #2
        RESTORE r3-r7
        SUB  r10, #16
        ADD  sp, r10
        JMP  r9

ap0:    MOV  r2, #0
        ADD  sp, #4
        JMP  r9
ap1:    RESTORE r3-r3
        MOV  r2, #1
        ADD  sp, #4
        JMP  r9
ap2:    RESTORE r3-r4
        MOV  r2, #2
        ADD  sp, #4
        JMP  r9
ap3:    RESTORE r3-r5
        MOV  r2, #3
        ADD  sp, #4
        JMP  r9
ap4:    RESTORE r3-r6
        MOV  r2, #4
        ADD  sp, #4
        JMP  r9
ap5:    RESTORE r3-r7
        MOV  r2, #5
        ADD  sp, #4
        JMP  r9
ap6:    RESTORE r3-r8
        MOV  r2, #6
        ADD  sp, #4
        JMP  r9

; apply_fun: apply_stack for an interpreted closure: r1 = it, r2 = 4n.
; Binds the parameters in a new frame and evaluates the body there.
apply_fun:
        MOV  r10, r2            ; 4n
        MOV  r4, [r1 + FUN_SHAPE]
        MOV  r11, r4
        AND  r11, #-4           ; 4 * required
        AND  r4, #2
        BNE  .rest
        CMP  r10, r11
        BNE  err_argc
        MOV  r2, r10            ; a frame of n pairs: 8 + 8n bytes
        ADD  r2, r10
        ADD  r2, #8
        BSR  alloc
        MOV  r3, r10            ; (1 + 2n) << 8 | B_FRAME
        LSL  r3, #7
        ADD  r3, #1 << 8 | B_FRAME
        ST   r3, [r1]
        MOV  r4, [sp + r10]     ; the closure (it may have moved)
        MOV  r3, [r4 + FUN_ENV]
        ST   r3, [r1 + 4]
        MOV  r5, [r4 + FUN_PARAMS]
        LEA  r6, [r1 + 8]
        MOV  r7, sp
.bind:  CMP  r5, r13
        BEQ  .bound
        MOV  r3, [r5 - 1]
        ST   r3, [r6]+
        MOV  r3, [r7]+
        ST   r3, [r6]+
        MOV  r5, [r5 + 3]
        BRA  .bind
.bound: OR   r1, #3
        MOV  r2, r1
        MOV  r1, [r4 + FUN_BODY]
        ADD  sp, r10
        ADD  sp, #4
        BRA  eval_body

.rest:  CMP  r10, r11
        BLO  err_argc
        MOV  r4, r13            ; the rest list, from the arguments after the required ones
        MOV  r12, r10
.rl:    CMP  r12, r11
        BLS  .rld
        SUB  r12, #4
        MOV  r3, [sp + r12]
        BSR  cons
        MOV  r4, r1
        BRA  .rl
.rld:   PUSH r4
        MOV  r2, r11            ; a frame of required + 1 pairs
        ADD  r2, r11
        ADD  r2, #16
        BSR  alloc
        MOV  r3, r11            ; (3 + 2 * required) << 8 | B_FRAME
        LSL  r3, #7
        ADD  r3, #3 << 8 | B_FRAME
        ST   r3, [r1]
        LEA  r7, [sp + 4]       ; the first argument
        MOV  r4, [r7 + r10]     ; the closure
        MOV  r3, [r4 + FUN_ENV]
        ST   r3, [r1 + 4]
        MOV  r5, [r4 + FUN_PARAMS]
        LEA  r6, [r1 + 8]
.rbind: MOV  r3, r5
        AND  r3, #3
        CMP  r3, #1
        BNE  .rlast
        MOV  r3, [r5 - 1]
        ST   r3, [r6]+
        MOV  r3, [r7]+
        ST   r3, [r6]+
        MOV  r5, [r5 + 3]
        BRA  .rbind
.rlast: ST   r5, [r6]+          ; the rest parameter
        MOV  r3, [sp]
        ST   r3, [r6]
        OR   r1, #3
        MOV  r2, r1
        MOV  r1, [r4 + FUN_BODY]
        ADD  sp, r10
        ADD  sp, #8
        BRA  eval_body

; interp_entry: the call slot of an interpreted closure, for calls through
; the calling convention (from primitives and compiled code).
interp_entry:
        PUSH r1
        CMP  r2, #6
        BHI  .many
        LSL  r2, #2
        JMP  [ie_tab + r2]
.many:  MOV  r9, r2             ; the arguments after the fifth are in the list r8
        SUB  r2, #5
        LSL  r2, #2
        SUB  sp, r2
        MOV  r10, sp
.fill:  CMP  r8, r13
        BEQ  .filled
        MOV  r11, [r8 - 1]
        ST   r11, [r10]+
        MOV  r8, [r8 + 3]
        BRA  .fill
.filled:
        SAVE r3-r7
        MOV  r2, r9
        LSL  r2, #2
        BRA  apply_fun
ie0:    BRA  apply_fun
ie1:    SAVE r3-r3
        BRA  apply_fun
ie2:    SAVE r3-r4
        BRA  apply_fun
ie3:    SAVE r3-r5
        BRA  apply_fun
ie4:    SAVE r3-r6
        BRA  apply_fun
ie5:    SAVE r3-r7
        BRA  apply_fun
ie6:    SAVE r3-r8
        BRA  apply_fun

; apply_list: r1 = a procedure, r2 = a list of arguments -> r1 = the result.
apply_list:
        PUSH r1
        MOV  r3, r2
        MOV  r4, #0
.len:   CMP  r3, r13
        BEQ  .lend
        MOV  r5, r3
        AND  r5, #3
        CMP  r5, #1
        BNE  .bad
        ADD  r4, #4
        MOV  r3, [r3 + 3]
        BRA  .len
.lend:  MOV  r5, sp
        SUB  r5, r4
        CMP  r5, [stack_limit]  ; room for the arguments?
        BLO  err_stack
        MOV  sp, r5
.fill:  CMP  r2, r13
        BEQ  .go
        MOV  r3, [r2 - 1]
        ST   r3, [r5]+
        MOV  r2, [r2 + 3]
        BRA  .fill
.go:    MOV  r2, r4
        BRA  apply_stack
.bad:   MOV  r1, r2
        BRA  err_notlist

; eval_one: eval, with the common cases (a variable, a constant) done
; without the dispatch.
eval_one:
        MOV  r3, r1
        AND  r3, #3
        CMP  r3, #1
        BEQ  eval
        CMP  r3, #3
        BNE  .self
        MOV  r3, byte [r1 - 3]
        CMP  r3, #B_SYM
        BEQ  ev_var
.self:  RET

; eval_into: evaluate a list of expressions into stack slots.
; r1 = the list, r2 = the environment, r3 = the first slot, r4 = 0 for
; expressions, 1 for let bindings (evaluate the cadr of each element).
eval_into:
        PUSH r4
        PUSH r2
        PUSH r3
        PUSH r1
.loop:  MOV  r5, [sp]
        CMP  r5, r13
        BEQ  .done
        MOV  r1, [r5 - 1]
        MOV  r5, [r5 + 3]
        ST   r5, [sp]
        MOV  r6, [sp + 12]
        BEQ  .expr
        MOV  r1, [r1 + 3]       ; (name init)
        MOV  r1, [r1 - 1]
.expr:  MOV  r2, [sp + 8]
        BSR  eval_one
        MOV  r5, [sp + 4]
        ST   r1, [r5]+
        ST   r5, [sp + 4]
        BRA  .loop
.done:  ADD  sp, #16
        RET

; eval_body: r1 = a list of expressions, r2 = an environment. The last one
; is a tail call.
eval_body:
        CMP  r1, r13
        BEQ  .nil
.loop:  MOV  r3, [r1 + 3]
        CMP  r3, r13
        BEQ  .last
        PUSH r2
        PUSH r3
        MOV  r1, [r1 - 1]
        BSR  eval
        POP  r1
        POP  r2
        BRA  .loop
.last:  MOV  r1, [r1 - 1]
        BRA  eval_t
.nil:   MOV  r1, r13
        RET

; make_fun: r1 = parameters, r2 = environment, r3 = body, r6 = the form
; (for errors) -> r1 = a closure. Checks the parameters and the body.
make_fun:
        MOV  r9, r1
        BSR  check_params
        BNE  .bad
        MOV  r9, r3
        BSR  proper
        BNE  .bad
        MOV  r4, #0             ; the shape
        MOV  r5, r1
.walk:  MOV  r9, r5
        AND  r9, #3
        CMP  r9, #1
        BNE  .end
        ADD  r4, #4
        MOV  r5, [r5 + 3]
        BRA  .walk
.end:   CMP  r5, r13
        BEQ  .shaped
        OR   r4, #2
.shaped:
        MOV  r5, r1
        MOV  r6, r2
        MOV  r2, #24
        BSR  alloc
        MOV  r7, #H_FUN
        ST   r7, [r1]
        MOV  r7, #interp_entry
        ST   r7, [r1 + 4]
        ST   r5, [r1 + 8]
        ST   r3, [r1 + 12]
        ST   r6, [r1 + 16]
        ST   r4, [r1 + 20]
        OR   r1, #3
        RET
.bad:   MOV  r1, r6
        BRA  err_syntax

; frame_find: r1 = a symbol, r2 = an environment -> r5 = the address of
; its value in the innermost frame that binds it, or 0. Keeps r1, r3.
frame_find:
.frame: CMP  r2, r13
        BEQ  .none
        MOV  r4, [r2 - 3]
        LSR  r4, #6
        AND  r4, #-4
        LEA  r4, [r2 + r4 + 1]
        LEA  r5, [r2 + 5]
.slot:  CMP  r5, r4
        BHS  .up
        CMP  r1, [r5]+
        BEQ  .found
        ADD  r5, #4
        BRA  .slot
.found: RET
.up:    MOV  r2, [r2 + 1]
        BRA  .frame
.none:  MOV  r5, #0
        RET

; ---- shape checks: they set Z for "yes" and use only r9-r12

; is_sym: r9 = a value -> Z set if it's a symbol. Uses r12.
is_sym: MOV  r12, r9
        AND  r12, #3
        CMP  r12, #3
        BNE  .ret
        CMP  r9, r13
        BEQ  .no
        MOV  r12, byte [r9 - 3]
        CMP  r12, #B_SYM
.ret:   RET
.no:    CMP  r9, #0             ; (nil isn't 0: Z clear)
        RET

; proper: r9 = a value -> Z set if it's a proper list. Uses r9, r10.
proper: CMP  r9, r13
        BEQ  .ret
        MOV  r10, r9
        AND  r10, #3
        CMP  r10, #1
        BNE  .ret
        MOV  r9, [r9 + 3]
        BRA  proper
.ret:   RET

; local: r9 = a symbol: mark it as having been a local's name. Uses r12.
local:  MOV  r12, [r9 + SYM_SPECIAL]
        OR   r12, #LOCAL
        ST   r12, [r9 + SYM_SPECIAL]
        RET

; check_params: r9 = a parameter list -> Z set if it's symbols, with a
; tail of nil or a symbol. Marks them as locals. Uses r9-r12.
check_params:
.loop:  MOV  r10, r9
        AND  r10, #3
        CMP  r10, #1
        BNE  .tail
        MOV  r11, r9
        MOV  r9, [r9 - 1]
        BSR  is_sym
        BNE  .ret
        BSR  local
        MOV  r9, [r11 + 3]
        BRA  .loop
.tail:  CMP  r9, r13
        BEQ  .ret
        BSR  is_sym
        BNE  .ret
        BSR  local
        CMP  r9, r9
.ret:   RET

; check_bindings: r9 = a let's bindings -> Z set if it's a proper list of
; (symbol init). Marks the symbols as locals. Uses r9-r12.
check_bindings:
.loop:  CMP  r9, r13
        BEQ  .ret
        MOV  r10, r9
        AND  r10, #3
        CMP  r10, #1
        BNE  .ret
        MOV  r11, [r9 - 1]      ; a binding
        MOV  r10, r11
        AND  r10, #3
        CMP  r10, #1
        BNE  .ret
        MOV  r10, [r11 + 3]     ; (init)
        MOV  r12, r10
        AND  r12, #3
        CMP  r12, #1
        BNE  .ret
        CMP  r13, [r10 + 3]
        BNE  .ret
        MOV  r10, r9
        MOV  r9, [r11 - 1]
        BSR  is_sym
        BNE  .ret
        BSR  local
        MOV  r9, [r10 + 3]
        BRA  .loop
.ret:   RET

; check_clauses: r9 = cond's clauses -> Z set if it's a proper list of
; non-empty proper lists. Uses r9-r11.
check_clauses:
.loop:  CMP  r9, r13
        BEQ  .ret
        MOV  r10, r9
        AND  r10, #3
        CMP  r10, #1
        BNE  .ret
        MOV  r11, r9
        MOV  r9, [r9 - 1]
        MOV  r10, r9
        AND  r10, #3
        CMP  r10, #1
        BNE  .ret
        BSR  proper
        BNE  .ret
        MOV  r9, [r11 + 3]
        BRA  .loop
.ret:   RET

; displace: r1 = a macro's expansion, r3 = the form it came from. The form
; becomes the expansion, so the macro is expanded only once.
displace:
        MOV  r4, r1
        AND  r4, #3
        CMP  r4, #1
        BNE  .wrap
        MOV  r4, [r1 - 1]
        ST   r4, [r3 - 1]
        MOV  r4, [r1 + 3]
        ST   r4, [r3 + 3]
        RET
.wrap:  PUSH r3                 ; not a pair: (begin expansion)
        MOV  r3, r1
        MOV  r4, r13
        BSR  cons
        POP  r3
        ST   r1, [r3 + 3]
        MOV  r4, #S_begin + 3
        ST   r4, [r3 - 1]
        RET

; ---- special forms: r1 = the form, r2 = the environment, r3 = the symbol.
; Each checks the whole form's shape before evaluating any of it.

sf_quote:
        MOV  r3, [r1 + 3]       ; (x)
        MOV  r9, r3
        AND  r9, #3
        CMP  r9, #1
        BNE  err_syntax
        CMP  r13, [r3 + 3]
        BNE  err_syntax
        MOV  r1, [r3 - 1]
        RET

sf_if:  MOV  r3, [r1 + 3]       ; (c a [b])
        MOV  r9, r3
        AND  r9, #3
        CMP  r9, #1
        BNE  err_syntax
        MOV  r4, [r3 + 3]       ; (a [b])
        MOV  r9, r4
        AND  r9, #3
        CMP  r9, #1
        BNE  err_syntax
        MOV  r5, [r4 + 3]       ; () or (b)
        CMP  r5, r13
        BEQ  .ok
        MOV  r9, r5
        AND  r9, #3
        CMP  r9, #1
        BNE  err_syntax
        CMP  r13, [r5 + 3]
        BNE  err_syntax
.ok:    PUSH r2
        PUSH r4
        MOV  r1, [r3 - 1]
        BSR  eval
        POP  r3
        POP  r2
        CMP  r1, r13
        BEQ  .else
        MOV  r1, [r3 - 1]
        BRA  eval_t
.else:  MOV  r3, [r3 + 3]
        CMP  r3, r13
        BEQ  .nil
        MOV  r1, [r3 - 1]
        BRA  eval_t
.nil:   MOV  r1, r13
        RET

sf_define:
        MOV  r6, r1             ; the form, for errors
        MOV  r3, [r1 + 3]       ; (name expr) or ((name . params) body...)
        MOV  r9, r3
        AND  r9, #3
        CMP  r9, #1
        BNE  .bad
        MOV  r4, [r3 - 1]
        MOV  r9, r4
        AND  r9, #3
        CMP  r9, #1
        BEQ  .fun
        MOV  r9, r4
        BSR  is_sym
        BNE  .bad
        MOV  r5, [r3 + 3]       ; (expr)
        MOV  r9, r5
        AND  r9, #3
        CMP  r9, #1
        BNE  .bad
        CMP  r13, [r5 + 3]
        BNE  .bad
        PUSH r4
        MOV  r1, [r5 - 1]
        BSR  eval
        POP  r4
        ST   r1, [r4 + SYM_VALUE]
        MOV  r1, r4
        RET
.fun:   MOV  r9, [r4 - 1]
        BSR  is_sym
        BNE  .bad
        PUSH r4
        MOV  r1, [r4 + 3]       ; the parameters
        MOV  r3, [r3 + 3]       ; the body
        BSR  make_fun
        POP  r4
        MOV  r4, [r4 - 1]
        ST   r1, [r4 + SYM_VALUE]
        MOV  r1, r4
        RET
.bad:   MOV  r1, r6
        BRA  err_syntax

sf_lambda:
        MOV  r6, r1
        MOV  r3, [r1 + 3]       ; (params body...)
        MOV  r9, r3
        AND  r9, #3
        CMP  r9, #1
        BNE  err_syntax
        MOV  r1, [r3 - 1]
        MOV  r3, [r3 + 3]
        BRA  make_fun

sf_set: MOV  r3, [r1 + 3]       ; (name expr)
        MOV  r9, r3
        AND  r9, #3
        CMP  r9, #1
        BNE  err_syntax
        MOV  r9, [r3 - 1]
        BSR  is_sym
        BNE  err_syntax
        MOV  r4, [r3 + 3]
        MOV  r9, r4
        AND  r9, #3
        CMP  r9, #1
        BNE  err_syntax
        CMP  r13, [r4 + 3]
        BNE  err_syntax
        PUSH r2
        MOV  r9, [r3 - 1]
        PUSH r9
        MOV  r1, [r4 - 1]
        BSR  eval
        MOV  r3, r1
        POP  r1
        POP  r2
        BSR  frame_find
        CMP  r5, #0
        BEQ  .global
        ST   r3, [r5]
        MOV  r1, r3
        RET
.global:
        ST   r3, [r1 + SYM_VALUE]
        MOV  r1, r3
        RET

sf_begin:
        MOV  r9, [r1 + 3]
        BSR  proper
        BNE  err_syntax
        MOV  r1, [r1 + 3]
        BRA  eval_body

sf_defmacro:
        MOV  r6, r1
        MOV  r3, [r1 + 3]       ; (name params body...)
        MOV  r9, r3
        AND  r9, #3
        CMP  r9, #1
        BNE  .bad
        MOV  r9, [r3 - 1]
        BSR  is_sym
        BNE  .bad
        MOV  r4, [r3 + 3]       ; (params body...)
        MOV  r9, r4
        AND  r9, #3
        CMP  r9, #1
        BNE  .bad
        MOV  r9, [r3 - 1]
        PUSH r9
        MOV  r1, [r4 - 1]
        MOV  r3, [r4 + 3]
        MOV  r2, r13
        BSR  make_fun
        POP  r4
        ST   r1, [r4 + SYM_MACRO]
        MOV  r1, [r4 + SYM_SPECIAL]
        AND  r1, #LOCAL
        OR   r1, #SF_MACRO
        ST   r1, [r4 + SYM_SPECIAL]
        MOV  r1, r4
        RET
.bad:   MOV  r1, r6
        BRA  err_syntax

; a macro call: expand it, put the expansion in place of the form, and
; evaluate that.
sf_macro:
        MOV  r9, [r1 + 3]
        BSR  proper
        BNE  err_syntax
        PUSH r2
        PUSH r1
        MOV  r2, [r1 + 3]       ; the arguments, unevaluated
        MOV  r1, [r3 + SYM_MACRO]
        BSR  apply_list
        MOV  r3, [sp]
        BSR  displace
        POP  r1
        POP  r2
        BRA  eval_t

sf_let: MOV  r6, r1
        MOV  r3, [r1 + 3]       ; (bindings body...)
        MOV  r9, r3
        AND  r9, #3
        CMP  r9, #1
        BNE  .bad
        MOV  r4, [r3 - 1]
        MOV  r9, r4
        BSR  is_sym
        BEQ  .named
        MOV  r9, r4
        BSR  check_bindings
        BNE  .bad
        MOV  r9, [r3 + 3]
        BSR  proper
        BNE  .bad
        PUSH r2                 ; the environment
        PUSH r3                 ; (bindings body...)
        MOV  r5, r4
        MOV  r6, r4             ; a zero slot per binding
        MOV  r4, #0
.zero:  CMP  r6, r13
        BEQ  .zd
        ST   r0, -[sp]
        ADD  r4, #4
        MOV  r6, [r6 + 3]
        BRA  .zero
.zd:    PUSH r4                 ; 4n
        MOV  r1, r5             ; the bindings
        LEA  r3, [sp + 4]
        MOV  r4, #1
        BSR  eval_into
        ; [sp] = 4n, [sp + 4 ...] = the values, then (bindings body...), the environment
        MOV  r10, [sp]
        MOV  r2, r10            ; a frame of n pairs
        ADD  r2, r10
        ADD  r2, #8
        BSR  alloc
        MOV  r3, r10
        LSL  r3, #7
        ADD  r3, #1 << 8 | B_FRAME
        ST   r3, [r1]
        LEA  r7, [sp + 4]       ; the values
        ADD  r10, r7            ; -> (bindings body...)
        MOV  r3, [r10 + 4]      ; the environment
        ST   r3, [r1 + 4]
        MOV  r5, [r10]
        MOV  r5, [r5 - 1]       ; the bindings
        LEA  r6, [r1 + 8]
.bind:  CMP  r5, r13
        BEQ  .bound
        MOV  r3, [r5 - 1]
        MOV  r3, [r3 - 1]       ; the name
        ST   r3, [r6]+
        MOV  r3, [r7]+
        ST   r3, [r6]+
        MOV  r5, [r5 + 3]
        BRA  .bind
.bound: OR   r1, #3
        MOV  r2, r1
        MOV  r1, [r10]
        MOV  r1, [r1 + 3]       ; the body
        LEA  sp, [r10 + 8]
        BRA  eval_body
.named: MOV  r5, [r3 + 3]       ; (bindings body...)
        MOV  r9, r5
        AND  r9, #3
        CMP  r9, #1
        BNE  .bad
        MOV  r9, [r5 - 1]
        BSR  check_bindings
        BNE  .bad
        MOV  r9, [r5 + 3]
        BSR  proper
        BNE  .bad
        PUSH r2                 ; rewrite it, by %named-let
        PUSH r1
        MOV  r3, r1
        MOV  r4, r13
        BSR  cons               ; (form)
        MOV  r2, r1
        MOV  r1, [S_named_let + 3 + SYM_VALUE]
        BSR  apply_list
        MOV  r3, [sp]
        BSR  displace
        POP  r1
        POP  r2
        BRA  eval_t
.bad:   MOV  r1, r6
        BRA  err_syntax

; let_shape: r1 = a let* or letrec form -> its bindings and body are
; checked; r3 = (bindings body...).
let_shape:
        MOV  r3, [r1 + 3]
        MOV  r9, r3
        AND  r9, #3
        CMP  r9, #1
        BNE  err_syntax
        MOV  r9, [r3 - 1]
        BSR  check_bindings
        BNE  err_syntax
        MOV  r9, [r3 + 3]
        BSR  proper
        BNE  err_syntax
        RET

sf_letstar:
        BSR  let_shape
        MOV  r4, [r3 + 3]
        PUSH r4                 ; [sp + 8] the body
        PUSH r2                 ; [sp + 4] the environment
        MOV  r4, [r3 - 1]
        PUSH r4                 ; [sp] the bindings left
.loop:  MOV  r4, [sp]
        CMP  r4, r13
        BEQ  .body
        MOV  r1, [r4 - 1]
        MOV  r1, [r1 + 3]
        MOV  r1, [r1 - 1]       ; the init
        MOV  r2, [sp + 4]
        BSR  eval
        MOV  r3, r1
        MOV  r2, #16            ; a frame of one pair
        BSR  alloc
        MOV  r4, #3 << 8 | B_FRAME
        ST   r4, [r1]
        MOV  r4, [sp + 4]
        ST   r4, [r1 + 4]
        MOV  r4, [sp]
        MOV  r5, [r4 - 1]
        MOV  r5, [r5 - 1]
        ST   r5, [r1 + 8]
        ST   r3, [r1 + 12]
        OR   r1, #3
        ST   r1, [sp + 4]
        MOV  r4, [r4 + 3]
        ST   r4, [sp]
        BRA  .loop
.body:  POP  r4
        POP  r2
        POP  r1
        BRA  eval_body

sf_letrec:
        BSR  let_shape
        PUSH r3                 ; (bindings body...)
        MOV  r5, [r3 - 1]
        MOV  r10, #0            ; a frame with every name bound to nil
        MOV  r6, r5
.cnt:   CMP  r6, r13
        BEQ  .cntd
        ADD  r10, #4
        MOV  r6, [r6 + 3]
        BRA  .cnt
.cntd:  MOV  r6, r2
        MOV  r2, r10
        ADD  r2, r10
        ADD  r2, #8
        BSR  alloc
        MOV  r3, r10
        LSL  r3, #7
        ADD  r3, #1 << 8 | B_FRAME
        ST   r3, [r1]
        ST   r6, [r1 + 4]
        MOV  r5, [sp]
        MOV  r5, [r5 - 1]
        LEA  r6, [r1 + 8]
.bind:  CMP  r5, r13
        BEQ  .bound
        MOV  r3, [r5 - 1]
        MOV  r3, [r3 - 1]
        ST   r3, [r6]+
        ST   r13, [r6]+
        MOV  r5, [r5 + 3]
        BRA  .bind
.bound: OR   r1, #3
        PUSH r1                 ; the frame
        MOV  r5, [sp + 4]
        MOV  r5, [r5 - 1]
        PUSH r5                 ; the bindings left
        MOV  r4, #12
        PUSH r4                 ; the next value's offset in the frame object
        ; [sp] offset, [sp + 4] bindings left, [sp + 8] frame, [sp + 12] (bindings body...)
.init:  MOV  r5, [sp + 4]
        CMP  r5, r13
        BEQ  .body
        MOV  r1, [r5 - 1]
        MOV  r1, [r1 + 3]
        MOV  r1, [r1 - 1]
        MOV  r5, [r5 + 3]
        ST   r5, [sp + 4]
        MOV  r2, [sp + 8]
        BSR  eval
        MOV  r2, [sp + 8]
        MOV  r4, [sp]
        ADD  r2, r4             ; frame + offset - 3: the value's address
        ST   r1, [r2 - 3]
        ADD  r4, #8
        ST   r4, [sp]
        BRA  .init
.body:  MOV  r2, [sp + 8]
        MOV  r1, [sp + 12]
        MOV  r1, [r1 + 3]
        ADD  sp, #16
        BRA  eval_body

sf_cond:
        MOV  r9, [r1 + 3]
        BSR  check_clauses
        BNE  err_syntax
        MOV  r3, [r1 + 3]       ; the clauses
.clause:
        CMP  r3, r13
        BEQ  .nil
        PUSH r2
        PUSH r3
        MOV  r1, [r3 - 1]
        MOV  r1, [r1 - 1]       ; the test
        BSR  eval
        POP  r3
        POP  r2
        CMP  r1, r13
        BNE  .hit
        MOV  r3, [r3 + 3]
        BRA  .clause
.hit:   MOV  r3, [r3 - 1]
        MOV  r3, [r3 + 3]
        CMP  r3, r13
        BEQ  .ret               ; no body: the test's value
        MOV  r1, r3
        BRA  eval_body
.nil:   MOV  r1, r13
.ret:   RET

sf_and: MOV  r9, [r1 + 3]
        BSR  proper
        BNE  err_syntax
        MOV  r3, [r1 + 3]
        CMP  r3, r13
        BEQ  .t
.loop:  MOV  r4, [r3 + 3]
        CMP  r4, r13
        BEQ  .last
        PUSH r2
        PUSH r4
        MOV  r1, [r3 - 1]
        BSR  eval
        POP  r3
        POP  r2
        CMP  r1, r13
        BNE  .loop
        RET
.last:  MOV  r1, [r3 - 1]
        BRA  eval_t
.t:     MOV  r1, #S_t + 3
        RET

sf_or:  MOV  r9, [r1 + 3]
        BSR  proper
        BNE  err_syntax
        MOV  r3, [r1 + 3]
        CMP  r3, r13
        BEQ  .nil
.loop:  MOV  r4, [r3 + 3]
        CMP  r4, r13
        BEQ  .last
        PUSH r2
        PUSH r4
        MOV  r1, [r3 - 1]
        BSR  eval
        POP  r3
        POP  r2
        CMP  r1, r13
        BEQ  .loop
        RET
.last:  MOV  r1, [r3 - 1]
        BRA  eval_t
.nil:   MOV  r1, r13
        RET
