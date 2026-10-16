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
; r6, r5, r4, r3, r8, r0 = arguments 1-6 (r7 is the link register); with
; more than 6, r6, r5, r4, r3 and r8 hold 1-5 and r0 a list of the rest. The call
; is CALL [r1 + 1], the procedure's call slot, which leaves the return
; address in r7. The result comes back in r1; r0-r12 are not preserved.
;
; Inside the interpreter, the return address is on the stack, where 1b's
; calls left it: eval pushes r7 when it evaluates a pair, the special forms
; are jumped to with it there and return with JMP [sp]+, and tail calls
; (eval_t, eval_body) leave it there. apply_stack pops it into r7 when it
; jumps to a procedure. An atom is a leaf: a constant or a variable comes
; back with RET, without touching the stack.

LOCAL   = 2                     ; the "has been a local" bit of the special field

; eval_t: eval for a tail call, with the return address on the stack.
eval_t: MOV  r6, r1
        AND  r6, #3
        CMP  r6, #1
        BEQ  ev_pair
        POP  r7
; eval_atom: r1 = a value that isn't a pair, r6 = its low two bits.
eval_atom:
        CMP  r6, #3
        BNE  .self              ; a number
        MOV  r6, byte [r1 - 3]
        CMP  r6, #B_SYM
        BEQ  ev_var
.self:  RET

; ev_var: r1 = a symbol, r2 = an environment -> r1 = its value. Uses r2,
; r5, r4.
ev_var: MOV  r5, [r1 + SYM_SPECIAL]
        AND  r5, #LOCAL
        BEQ  .global
        CMP  r2, r13
        BEQ  .global
.frame: MOV  r5, [r2 - 3]       ; (1 + 2k) << 8 | ...
        LSR  r5, #6
        AND  r5, #-4            ; 4 + 8k
        LEA  r5, [r2 + r5 + 1]  ; the end of the frame
        LEA  r4, [r2 + 5]       ; the first name
.slot:  CMP  r4, r5
        BHS  .up
        CMP  r1, [r4]+
        BEQ  .found
        ADD  r4, #4
        BRA  .slot
.found: MOV  r1, [r4]
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

; eval: r1 = an expression, r2 = an environment -> r1 = its value. A pair
; puts the return address on the stack, checks the stack and goes on in
; ev_pair. (eval_one is 1b's eval without the stack check for an atom,
; which eval is too now.)
eval:
eval_one:
        MOV  r6, r1
        AND  r6, #3
        CMP  r6, #1
        BNE  eval_atom
        PUSH r7
        CMP  sp, [stack_limit]
        BLO  err_stack

; ev_pair: r1 = a form (a pair), r2 = an environment; the return address
; on the stack.
ev_pair:
        MOV  r6, [r1 - 1]       ; the operator
        MOV  r5, r6
        AND  r5, #3
        CMP  r5, #3
        BNE  ev_app
        MOV  r5, byte [r6 - 3]
        CMP  r5, #B_SYM
        BNE  ev_app
        MOV  r5, [r6 + SYM_SPECIAL]
        AND  r5, #-4
        BEQ  ev_app
        JMP  [sf_handlers + r5] ; r1 = the form, r2 = the environment, r6 = its symbol

; ev_app: a call. r1 = the form, r2 = the environment, r6 = the operator.
; The arguments must be a proper list, checked before anything is
; evaluated.
ev_app: MOV  r4, [r1 + 3]       ; the argument expressions
        MOV  r3, r4
        MOV  r5, #0
.cnt:   CMP  r3, r13
        BEQ  .cntd
        MOV  r9, r3
        AND  r9, #3
        CMP  r9, #1
        BNE  err_syntax
        ADD  r5, #4
        MOV  r3, [r3 + 3]
        BRA  .cnt
.cntd:  PUSH r2
        PUSH r4
        PUSH r5                 ; 4n
        MOV  r1, r6
        BSR  eval_one           ; the procedure
        POP  r5
        POP  r4
        POP  r2
        PUSH r1
        MOV  r6, sp             ; the procedure's slot: the first argument goes below it
        MOV  r3, r5             ; a zero slot per argument
.zero:  SUB  r3, #4
        BLO  .zd
        CLR  -[sp]
        BRA  .zero
.zd:    PUSH r5
        MOV  r1, r4
        MOV  r5, #0
        BSR  eval_into
        POP  r2
        ; fall through

; apply_stack: apply [sp + 4n] to the n arguments below it, the first at
; [sp + 4n - 4] and the last at [sp], so that RESTORE r(7-n)-r6 loads them
; (n <= 4); r2 = 4n. They're taken off the stack. Jumped to, not called: the
; procedure returns to whoever is below them on the stack, whose address
; goes into r7 as the procedure is jumped to.
apply_stack:
        MOV  r1, [sp + r2]      ; the procedure
        MOV  r9, [r1 + CALL_SLOT]   ; its code (and the type check)
        CMP  r9, #interp_entry
        BEQ  apply_fun
        CMP  r2, #24
        BHI  .many
        JMP  [ap_tab + r2]
.many:  MOV  r10, r2            ; arguments 6..n go in a list, made from the last
        MOV  r11, r2
        SUB  r11, #20           ; 4 * (n - 5): arguments 6..n, from [sp] up
        MOV  r5, r13
        MOV  r12, #0
.mk:    MOV  r6, [sp + r12]
        BSR  cons
        MOV  r5, r1
        ADD  r12, #4
        CMP  r12, r11
        BLO  .mk
        MOV  r0, r5
        MOV  r1, [sp + r10]     ; (it may have moved)
        MOV  r2, r10
        LSR  r2, #2
        ADD  sp, r11
        POP  r8
        RESTORE r3-r6
        ADD  sp, #4
        POP  r7
        JMP  r9

ap0:    MOV  r2, #0
        ADD  sp, #4
        POP  r7
        JMP  r9
ap1:    POP  r6
        MOV  r2, #1
        ADD  sp, #4
        POP  r7
        JMP  r9
ap2:    RESTORE r5-r6
        MOV  r2, #2
        ADD  sp, #4
        POP  r7
        JMP  r9
ap3:    RESTORE r4-r6
        MOV  r2, #3
        ADD  sp, #4
        POP  r7
        JMP  r9
ap4:    RESTORE r3-r6
        MOV  r2, #4
        ADD  sp, #4
        POP  r7
        JMP  r9
ap5:    POP  r8
        RESTORE r3-r6
        MOV  r2, #5
        ADD  sp, #4
        POP  r7
        JMP  r9
ap6:    POP  r0
        POP  r8
        RESTORE r3-r6
        MOV  r2, #6
        ADD  sp, #4
        POP  r7
        JMP  r9

; apply_fun: apply_stack for an interpreted closure: r1 = it, r2 = 4n.
; Binds the parameters in a new frame and evaluates the body there.
apply_fun:
        MOV  r10, r2            ; 4n
        MOV  r5, [r1 + FUN_SHAPE]
        MOV  r11, r5
        AND  r11, #-4           ; 4 * required
        AND  r5, #2
        BNE  .rest
        CMP  r10, r11
        BNE  err_argc
        MOV  r2, r10            ; a frame of n pairs: 8 + 8n bytes
        ADD  r2, r10
        ADD  r2, #8
        BSR  alloc
        MOV  r6, r10            ; (1 + 2n) << 8 | B_FRAME
        LSL  r6, #7
        ADD  r6, #1 << 8 | B_FRAME
        MOV  [r1], r6
        LEA  r8, [sp + r10]     ; the closure (it may have moved), just above
        MOV  r5, [r8]           ; the first argument
        MOV  r6, [r5 + FUN_ENV]
        MOV  [r1 + 4], r6
        MOV  r4, [r5 + FUN_PARAMS]
        LEA  r3, [r1 + 8]
.bind:  CMP  r4, r13
        BEQ  .bound
        MOV  r6, [r4 - 1]
        MOV  [r3]+, r6
        MOV  r6, -[r8]
        MOV  [r3]+, r6
        MOV  r4, [r4 + 3]
        BRA  .bind
.bound: OR   r1, #3
        MOV  r2, r1
        MOV  r1, [r5 + FUN_BODY]
        ADD  sp, r10
        ADD  sp, #4
        BRA  eval_body

.rest:  CMP  r10, r11
        BLO  err_argc
        MOV  r5, r13            ; the rest list, from the arguments after the required ones
        MOV  r9, r10            ; (the last at [sp])
        SUB  r9, r11
        MOV  r12, #0
.rl:    CMP  r12, r9
        BHS  .rld
        MOV  r6, [sp + r12]
        BSR  cons
        MOV  r5, r1
        ADD  r12, #4
        BRA  .rl
.rld:   PUSH r5
        MOV  r2, r11            ; a frame of required + 1 pairs
        ADD  r2, r11
        ADD  r2, #16
        BSR  alloc
        MOV  r6, r11            ; (3 + 2 * required) << 8 | B_FRAME
        LSL  r6, #7
        ADD  r6, #3 << 8 | B_FRAME
        MOV  [r1], r6
        LEA  r8, [sp + r10 + 4] ; the closure, just above the first argument
        MOV  r5, [r8]
        MOV  r6, [r5 + FUN_ENV]
        MOV  [r1 + 4], r6
        MOV  r4, [r5 + FUN_PARAMS]
        LEA  r3, [r1 + 8]
.rbind: MOV  r6, r4
        AND  r6, #3
        CMP  r6, #1
        BNE  .rlast
        MOV  r6, [r4 - 1]
        MOV  [r3]+, r6
        MOV  r6, -[r8]
        MOV  [r3]+, r6
        MOV  r4, [r4 + 3]
        BRA  .rbind
.rlast: MOV  [r3]+, r4          ; the rest parameter
        MOV  r6, [sp]
        MOV  [r3], r6
        OR   r1, #3
        MOV  r2, r1
        MOV  r1, [r5 + FUN_BODY]
        ADD  sp, r10
        ADD  sp, #8
        BRA  eval_body

; interp_entry: the call slot of an interpreted closure, for calls through
; the calling convention (from primitives and compiled code). The return
; address goes on the stack, below the closure and the arguments, as
; apply_fun wants them.
interp_entry:
        PUSH r7
        PUSH r1
        CMP  r2, #6
        BHI  .many
        LSL  r2, #2
        JMP  [ie_tab + r2]
.many:  SAVE r3-r6              ; arguments 1-4, 5, then the rest from the list r0
        PUSH r8
        LSL  r2, #2
.fill:  CMP  r0, r13
        BEQ  apply_fun
        MOV  r11, [r0 - 1]
        PUSH r11
        MOV  r0, [r0 + 3]
        BRA  .fill
ie0:    BRA  apply_fun
ie1:    PUSH r6
        BRA  apply_fun
ie2:    SAVE r5-r6
        BRA  apply_fun
ie3:    SAVE r4-r6
        BRA  apply_fun
ie4:    SAVE r3-r6
        BRA  apply_fun
ie5:    SAVE r3-r6
        PUSH r8
        BRA  apply_fun
ie6:    SAVE r3-r6
        PUSH r8
        PUSH r0
        BRA  apply_fun

; apply_list: r1 = a procedure, r2 = a list of arguments -> r1 = the result.
apply_list:
        PUSH r7
apply_list_t:
        PUSH r1
        MOV  r6, r2
        MOV  r5, #0
.len:   CMP  r6, r13
        BEQ  .lend
        MOV  r4, r6
        AND  r4, #3
        CMP  r4, #1
        BNE  .bad
        ADD  r5, #4
        MOV  r6, [r6 + 3]
        BRA  .len
.lend:  MOV  r4, sp
        SUB  r4, r5
        CMP  r4, [stack_limit]  ; room for the arguments?
        BLO  err_stack
.fill:  CMP  r2, r13
        BEQ  .go
        MOV  r6, [r2 - 1]
        PUSH r6                 ; the first deepest
        MOV  r2, [r2 + 3]
        BRA  .fill
.go:    MOV  r2, r5
        BRA  apply_stack
.bad:   MOV  r1, r2
        BRA  err_notlist

; eval_into: evaluate a list of expressions into stack slots, the first
; expression's highest. r1 = the list, r2 = the environment, r6 = the
; address just above the first slot, r5 = 0 for expressions, 1 for let
; bindings (evaluate the cadr of each element).
eval_into:
        PUSH r7
        PUSH r5
        PUSH r2
        PUSH r6
        PUSH r1
.loop:  MOV  r4, [sp]
        CMP  r4, r13
        BEQ  .done
        MOV  r1, [r4 - 1]
        MOV  r4, [r4 + 3]
        MOV  [sp], r4
        MOVS r3, [sp + 12]
        BEQ  .expr
        MOV  r1, [r1 + 3]       ; (name init)
        MOV  r1, [r1 - 1]
.expr:  MOV  r2, [sp + 8]
        BSR  eval_one
        MOV  r4, [sp + 4]
        MOV  -[r4], r1
        MOV  [sp + 4], r4
        BRA  .loop
.done:  ADD  sp, #16
        JMP  [sp]+

; eval_body: r1 = a list of expressions, r2 = an environment. The last one
; is a tail call. Jumped to with the return address on the stack.
eval_body:
        CMP  r1, r13
        BEQ  .nil
.loop:  MOV  r6, [r1 + 3]
        CMP  r6, r13
        BEQ  .last
        PUSH r2
        PUSH r6
        MOV  r1, [r1 - 1]
        BSR  eval
        POP  r1
        POP  r2
        BRA  .loop
.last:  MOV  r1, [r1 - 1]
        BRA  eval_t
.nil:   MOV  r1, r13
        JMP  [sp]+

; make_fun: r1 = parameters, r2 = environment, r6 = body, r3 = the form
; (for errors) -> r1 = a closure. Checks the parameters and the body.
make_fun:
        PUSH r7
make_fun_t:
        MOV  r9, r1
        BSR  check_params
        BNE  .bad
        MOV  r9, r6
        BSR  proper
        BNE  .bad
        MOV  r5, #0             ; the shape
        MOV  r4, r1
.walk:  MOV  r9, r4
        AND  r9, #3
        CMP  r9, #1
        BNE  .end
        ADD  r5, #4
        MOV  r4, [r4 + 3]
        BRA  .walk
.end:   CMP  r4, r13
        BEQ  .shaped
        OR   r5, #2
.shaped:
        MOV  r4, r1
        MOV  r3, r2
        MOV  r2, #24
        BSR  alloc
        MOV  r9, #H_FUN
        MOV  [r1], r9
        MOV  r9, #interp_entry
        MOV  [r1 + 4], r9
        MOV  [r1 + 8], r4
        MOV  [r1 + 12], r6
        MOV  [r1 + 16], r3
        MOV  [r1 + 20], r5
        OR   r1, #3
        JMP  [sp]+
.bad:   MOV  r1, r3
        BRA  err_syntax

; frame_find: r1 = a symbol, r2 = an environment -> r4 = the address of
; its value in the innermost frame that binds it, or 0. Keeps r1, r6.
frame_find:
.frame: CMP  r2, r13
        BEQ  .none
        MOV  r5, [r2 - 3]
        LSR  r5, #6
        AND  r5, #-4
        LEA  r5, [r2 + r5 + 1]
        LEA  r4, [r2 + 5]
.slot:  CMP  r4, r5
        BHS  .up
        CMP  r1, [r4]+
        BEQ  .found
        ADD  r4, #4
        BRA  .slot
.found: RET
.up:    MOV  r2, [r2 + 1]
        BRA  .frame
.none:  MOV  r4, #0
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
        MOV  [r9 + SYM_SPECIAL], r12
        RET

; check_params: r9 = a parameter list -> Z set if it's symbols, with a
; tail of nil or a symbol. Marks them as locals. Uses r9-r12.
check_params:
        PUSH r7
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
.ret:   JMP  [sp]+

; check_bindings: r9 = a let's bindings -> Z set if it's a proper list of
; (symbol init). Marks the symbols as locals. Uses r9-r12.
check_bindings:
        PUSH r7
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
.ret:   JMP  [sp]+

; check_clauses: r9 = cond's clauses -> Z set if it's a proper list of
; non-empty proper lists. Uses r9-r11.
check_clauses:
        PUSH r7
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
.ret:   JMP  [sp]+

; displace: r1 = a macro's expansion, r6 = the form it came from. The form
; becomes the expansion, so the macro is expanded only once.
displace:
        MOV  r5, r1
        AND  r5, #3
        CMP  r5, #1
        BNE  .wrap
        MOV  r5, [r1 - 1]
        MOV  [r6 - 1], r5
        MOV  r5, [r1 + 3]
        MOV  [r6 + 3], r5
        RET
.wrap:  PUSH r7
        PUSH r6                 ; not a pair: (begin expansion)
        MOV  r6, r1
        MOV  r5, r13
        BSR  cons
        POP  r6
        POP  r7
        MOV  [r6 + 3], r1
        MOV  r5, #S_begin + 3
        MOV  [r6 - 1], r5
        RET

; ---- special forms: r1 = the form, r2 = the environment, r6 = the symbol.
; Each checks the whole form's shape before evaluating any of it. They're
; jumped to with the return address on the stack.

sf_quote:
        MOV  r6, [r1 + 3]       ; (x)
        MOV  r9, r6
        AND  r9, #3
        CMP  r9, #1
        BNE  err_syntax
        CMP  r13, [r6 + 3]
        BNE  err_syntax
        MOV  r1, [r6 - 1]
        JMP  [sp]+

sf_if:  MOV  r6, [r1 + 3]       ; (c a [b])
        MOV  r9, r6
        AND  r9, #3
        CMP  r9, #1
        BNE  err_syntax
        MOV  r5, [r6 + 3]       ; (a [b])
        MOV  r9, r5
        AND  r9, #3
        CMP  r9, #1
        BNE  err_syntax
        MOV  r4, [r5 + 3]       ; () or (b)
        CMP  r4, r13
        BEQ  .ok
        MOV  r9, r4
        AND  r9, #3
        CMP  r9, #1
        BNE  err_syntax
        CMP  r13, [r4 + 3]
        BNE  err_syntax
.ok:    PUSH r2
        PUSH r5
        MOV  r1, [r6 - 1]
        BSR  eval
        POP  r6
        POP  r2
        CMP  r1, r13
        BEQ  .else
        MOV  r1, [r6 - 1]
        BRA  eval_t
.else:  MOV  r6, [r6 + 3]
        CMP  r6, r13
        BEQ  .nil
        MOV  r1, [r6 - 1]
        BRA  eval_t
.nil:   MOV  r1, r13
        JMP  [sp]+

sf_define:
        MOV  r3, r1             ; the form, for errors
        MOV  r6, [r1 + 3]       ; (name expr) or ((name . params) body...)
        MOV  r9, r6
        AND  r9, #3
        CMP  r9, #1
        BNE  .bad
        MOV  r5, [r6 - 1]
        MOV  r9, r5
        AND  r9, #3
        CMP  r9, #1
        BEQ  .fun
        MOV  r9, r5
        BSR  is_sym
        BNE  .bad
        MOV  r4, [r6 + 3]       ; (expr)
        MOV  r9, r4
        AND  r9, #3
        CMP  r9, #1
        BNE  .bad
        CMP  r13, [r4 + 3]
        BNE  .bad
        PUSH r5
        MOV  r1, [r4 - 1]
        BSR  eval
        POP  r5
        MOV  [r5 + SYM_VALUE], r1
        MOV  r1, r5
        JMP  [sp]+
.fun:   MOV  r9, [r5 - 1]
        BSR  is_sym
        BNE  .bad
        PUSH r5
        MOV  r1, [r5 + 3]       ; the parameters
        MOV  r6, [r6 + 3]       ; the body
        BSR  make_fun
        POP  r5
        MOV  r5, [r5 - 1]
        MOV  [r5 + SYM_VALUE], r1
        MOV  r1, r5
        JMP  [sp]+
.bad:   MOV  r1, r3
        BRA  err_syntax

sf_lambda:
        MOV  r3, r1
        MOV  r6, [r1 + 3]       ; (params body...)
        MOV  r9, r6
        AND  r9, #3
        CMP  r9, #1
        BNE  err_syntax
        MOV  r1, [r6 - 1]
        MOV  r6, [r6 + 3]
        BRA  make_fun_t

sf_set: MOV  r6, [r1 + 3]       ; (name expr)
        MOV  r9, r6
        AND  r9, #3
        CMP  r9, #1
        BNE  err_syntax
        MOV  r9, [r6 - 1]
        BSR  is_sym
        BNE  err_syntax
        MOV  r5, [r6 + 3]
        MOV  r9, r5
        AND  r9, #3
        CMP  r9, #1
        BNE  err_syntax
        CMP  r13, [r5 + 3]
        BNE  err_syntax
        PUSH r2
        MOV  r9, [r6 - 1]
        PUSH r9
        MOV  r1, [r5 - 1]
        BSR  eval
        MOV  r6, r1
        POP  r1
        POP  r2
        BSR  frame_find
        CMP  r4, #0
        BEQ  .global
        MOV  [r4], r6
        MOV  r1, r6
        JMP  [sp]+
.global:
        MOV  [r1 + SYM_VALUE], r6
        MOV  r1, r6
        JMP  [sp]+

sf_begin:
        MOV  r9, [r1 + 3]
        BSR  proper
        BNE  err_syntax
        MOV  r1, [r1 + 3]
        BRA  eval_body

sf_defmacro:
        MOV  r3, r1
        MOV  r6, [r1 + 3]       ; (name params body...)
        MOV  r9, r6
        AND  r9, #3
        CMP  r9, #1
        BNE  .bad
        MOV  r9, [r6 - 1]
        BSR  is_sym
        BNE  .bad
        MOV  r5, [r6 + 3]       ; (params body...)
        MOV  r9, r5
        AND  r9, #3
        CMP  r9, #1
        BNE  .bad
        MOV  r9, [r6 - 1]
        PUSH r9
        MOV  r1, [r5 - 1]
        MOV  r6, [r5 + 3]
        MOV  r2, r13
        BSR  make_fun
        POP  r5
        MOV  [r5 + SYM_MACRO], r1
        MOV  r1, [r5 + SYM_SPECIAL]
        AND  r1, #LOCAL
        OR   r1, #SF_MACRO
        MOV  [r5 + SYM_SPECIAL], r1
        MOV  r1, r5
        JMP  [sp]+
.bad:   MOV  r1, r3
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
        MOV  r1, [r6 + SYM_MACRO]
        BSR  apply_list
        MOV  r6, [sp]
        BSR  displace
        POP  r1
        POP  r2
        BRA  eval_t

sf_let: MOV  r3, r1
        MOV  r6, [r1 + 3]       ; (bindings body...)
        MOV  r9, r6
        AND  r9, #3
        CMP  r9, #1
        BNE  .bad
        MOV  r5, [r6 - 1]
        MOV  r9, r5
        BSR  is_sym
        BEQ  .named
        MOV  r9, r5
        BSR  check_bindings
        BNE  .bad
        MOV  r9, [r6 + 3]
        BSR  proper
        BNE  .bad
        PUSH r2                 ; the environment
        PUSH r6                 ; (bindings body...)
        MOV  r4, r5
        MOV  r3, r5             ; a zero slot per binding
        MOV  r5, #0
.zero:  CMP  r3, r13
        BEQ  .zd
        CLR  -[sp]
        ADD  r5, #4
        MOV  r3, [r3 + 3]
        BRA  .zero
.zd:    PUSH r5                 ; 4n
        MOV  r1, r4             ; the bindings
        LEA  r6, [sp + r5 + 4]
        MOV  r5, #1
        BSR  eval_into
        ; [sp] = 4n, [sp + 4 ...] = the values (the first highest), then
        ; (bindings body...), the environment
        MOV  r10, [sp]
        MOV  r2, r10            ; a frame of n pairs
        ADD  r2, r10
        ADD  r2, #8
        BSR  alloc
        MOV  r6, r10
        LSL  r6, #7
        ADD  r6, #1 << 8 | B_FRAME
        MOV  [r1], r6
        LEA  r10, [sp + r10 + 4] ; -> (bindings body...)
        MOV  r8, r10            ; just above the first value
        MOV  r6, [r10 + 4]      ; the environment
        MOV  [r1 + 4], r6
        MOV  r4, [r10]
        MOV  r4, [r4 - 1]       ; the bindings
        LEA  r3, [r1 + 8]
.bind:  CMP  r4, r13
        BEQ  .bound
        MOV  r6, [r4 - 1]
        MOV  r6, [r6 - 1]       ; the name
        MOV  [r3]+, r6
        MOV  r6, -[r8]
        MOV  [r3]+, r6
        MOV  r4, [r4 + 3]
        BRA  .bind
.bound: OR   r1, #3
        MOV  r2, r1
        MOV  r1, [r10]
        MOV  r1, [r1 + 3]       ; the body
        LEA  sp, [r10 + 8]
        BRA  eval_body
.named: MOV  r4, [r6 + 3]       ; (bindings body...)
        MOV  r9, r4
        AND  r9, #3
        CMP  r9, #1
        BNE  .bad
        MOV  r9, [r4 - 1]
        BSR  check_bindings
        BNE  .bad
        MOV  r9, [r4 + 3]
        BSR  proper
        BNE  .bad
        PUSH r2                 ; rewrite it, by %named-let
        PUSH r1
        MOV  r6, r1
        MOV  r5, r13
        BSR  cons               ; (form)
        MOV  r2, r1
        MOV  r1, [S_named_let + 3 + SYM_VALUE]
        BSR  apply_list
        MOV  r6, [sp]
        BSR  displace
        POP  r1
        POP  r2
        BRA  eval_t
.bad:   MOV  r1, r3
        BRA  err_syntax

; let_shape: r1 = a let* or letrec form -> its bindings and body are
; checked; r6 = (bindings body...).
let_shape:
        PUSH r7
        MOV  r6, [r1 + 3]
        MOV  r9, r6
        AND  r9, #3
        CMP  r9, #1
        BNE  err_syntax
        MOV  r9, [r6 - 1]
        BSR  check_bindings
        BNE  err_syntax
        MOV  r9, [r6 + 3]
        BSR  proper
        BNE  err_syntax
        JMP  [sp]+

sf_letstar:
        BSR  let_shape
        MOV  r5, [r6 + 3]
        PUSH r5                 ; [sp + 8] the body
        PUSH r2                 ; [sp + 4] the environment
        MOV  r5, [r6 - 1]
        PUSH r5                 ; [sp] the bindings left
.loop:  MOV  r5, [sp]
        CMP  r5, r13
        BEQ  .body
        MOV  r1, [r5 - 1]
        MOV  r1, [r1 + 3]
        MOV  r1, [r1 - 1]       ; the init
        MOV  r2, [sp + 4]
        BSR  eval
        MOV  r6, r1
        MOV  r2, #16            ; a frame of one pair
        BSR  alloc
        MOV  r5, #3 << 8 | B_FRAME
        MOV  [r1], r5
        MOV  r5, [sp + 4]
        MOV  [r1 + 4], r5
        MOV  r5, [sp]
        MOV  r4, [r5 - 1]
        MOV  r4, [r4 - 1]
        MOV  [r1 + 8], r4
        MOV  [r1 + 12], r6
        OR   r1, #3
        MOV  [sp + 4], r1
        MOV  r5, [r5 + 3]
        MOV  [sp], r5
        BRA  .loop
.body:  POP  r5
        POP  r2
        POP  r1
        BRA  eval_body

sf_letrec:
        BSR  let_shape
        PUSH r6                 ; (bindings body...)
        MOV  r4, [r6 - 1]
        MOV  r10, #0            ; a frame with every name bound to nil
        MOV  r3, r4
.cnt:   CMP  r3, r13
        BEQ  .cntd
        ADD  r10, #4
        MOV  r3, [r3 + 3]
        BRA  .cnt
.cntd:  MOV  r3, r2
        MOV  r2, r10
        ADD  r2, r10
        ADD  r2, #8
        BSR  alloc
        MOV  r6, r10
        LSL  r6, #7
        ADD  r6, #1 << 8 | B_FRAME
        MOV  [r1], r6
        MOV  [r1 + 4], r3
        MOV  r4, [sp]
        MOV  r4, [r4 - 1]
        LEA  r3, [r1 + 8]
.bind:  CMP  r4, r13
        BEQ  .bound
        MOV  r6, [r4 - 1]
        MOV  r6, [r6 - 1]
        MOV  [r3]+, r6
        MOV  [r3]+, r13
        MOV  r4, [r4 + 3]
        BRA  .bind
.bound: OR   r1, #3
        PUSH r1                 ; the frame
        MOV  r4, [sp + 4]
        MOV  r4, [r4 - 1]
        PUSH r4                 ; the bindings left
        MOV  r5, #12
        PUSH r5                 ; the next value's offset in the frame object
        ; [sp] offset, [sp + 4] bindings left, [sp + 8] frame, [sp + 12] (bindings body...)
.init:  MOV  r4, [sp + 4]
        CMP  r4, r13
        BEQ  .body
        MOV  r1, [r4 - 1]
        MOV  r1, [r1 + 3]
        MOV  r1, [r1 - 1]
        MOV  r4, [r4 + 3]
        MOV  [sp + 4], r4
        MOV  r2, [sp + 8]
        BSR  eval
        MOV  r2, [sp + 8]
        MOV  r5, [sp]
        ADD  r2, r5             ; frame + offset - 3: the value's address
        MOV  [r2 - 3], r1
        ADD  r5, #8
        MOV  [sp], r5
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
        MOV  r6, [r1 + 3]       ; the clauses
.clause:
        CMP  r6, r13
        BEQ  .nil
        PUSH r2
        PUSH r6
        MOV  r1, [r6 - 1]
        MOV  r1, [r1 - 1]       ; the test
        BSR  eval
        POP  r6
        POP  r2
        CMP  r1, r13
        BNE  .hit
        MOV  r6, [r6 + 3]
        BRA  .clause
.hit:   MOV  r6, [r6 - 1]
        MOV  r6, [r6 + 3]
        CMP  r6, r13
        BEQ  .ret               ; no body: the test's value
        MOV  r1, r6
        BRA  eval_body
.nil:   MOV  r1, r13
.ret:   JMP  [sp]+

sf_and: MOV  r9, [r1 + 3]
        BSR  proper
        BNE  err_syntax
        MOV  r6, [r1 + 3]
        CMP  r6, r13
        BEQ  .t
.loop:  MOV  r5, [r6 + 3]
        CMP  r5, r13
        BEQ  .last
        PUSH r2
        PUSH r5
        MOV  r1, [r6 - 1]
        BSR  eval
        POP  r6
        POP  r2
        CMP  r1, r13
        BNE  .loop
        JMP  [sp]+
.last:  MOV  r1, [r6 - 1]
        BRA  eval_t
.t:     MOV  r1, #S_t + 3
        JMP  [sp]+

sf_or:  MOV  r9, [r1 + 3]
        BSR  proper
        BNE  err_syntax
        MOV  r6, [r1 + 3]
        CMP  r6, r13
        BEQ  .nil
.loop:  MOV  r5, [r6 + 3]
        CMP  r5, r13
        BEQ  .last
        PUSH r2
        PUSH r5
        MOV  r1, [r6 - 1]
        BSR  eval
        POP  r6
        POP  r2
        CMP  r1, r13
        BEQ  .loop
        JMP  [sp]+
.last:  MOV  r1, [r6 - 1]
        BRA  eval_t
.nil:   MOV  r1, r13
        JMP  [sp]+
