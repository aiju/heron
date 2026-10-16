; Egret's interpreter loop for draft 2, by hand: the bytecodes that run
; most, and the common case of a send. Anything else (a method cache miss,
; *rest, new, errors, the rarer bytecodes) goes to the C interpreter's
; single-stepper, egret_step: interp.c built with EGRET_ASM, which runs
; one bytecode on the registers saved in a VMState and hands back.
;
; build.py puts the C headers' constants in front of this file (field
; numbers, opcodes, the Frame and VMState layouts) and the dispatch table
; after it: entry n is op_<name of opcode n>, or op_slow if there's no
; such label here.
;
; Registers, while the loop runs:
;   r8   ip, the next bytecode
;   r9   bp: the frame's receiver slot; slot i is [r9 + 4i]
;   r10  the value stack's next free slot, so the top is [r10 - 4]
;        (VMState.sp and vm_sp point at the top value itself)
;   r11  nil
;   r12  the method's literals
;   r13  the dispatch table
;   r14  the frame record: the current object, whose fields mode E,
;        [r14 + 4R], reaches in one parcel
;   r0-r7 scratch; C calls keep r8-r14, and leave their return address
;        in r7, the link register: nothing is kept in r7 across one
;
; Every handler ends with the dispatch, two instructions:
;       MOV  r1, byte [r8]+
;       JMP  [r13 + r1*4]

        .global _asm_run, _mcache_cls, _mcache_sel, _mcache_method, _egret_save
        .far optable

        .section .bss.egret_mcache
        .align 4                ; the method cache (interp.c): three arrays
_mcache_cls: .space 4 * 1024
_mcache_sel: .space 4 * 1024
_mcache_method: .space 4 * 1024

        .section .text.egret_interp

; int asm_run(VMState *st): run until the first frame returns (STEP_RETURNED)
; or an error nobody catches ends it (STEP_ERROR).
_asm_run:
        SAVE r7-r14
        MOV  r2, [_egret_st]
        PUSH r2
        MOV  [_egret_st], r1
        MOV  r13, #optable
        MOV  r11, #NIL
        BRA  reload

exit:   POP  r2
        MOV  [_egret_st], r2
        RESTORE r7-r14
        RET

; ---- the slow path -------------------------------------------------------------

; save: the registers into egret_st (returns it in r1)
_egret_save:
save:   MOV  r1, [_egret_st]
        LEA  r2, [r10 - 4]
        MOV  [r1 + VS_SP], r2
        MOV  [r1 + VS_BP], r9
        MOV  [r1 + VS_FP], r14
        MOV  [r1 + VS_IP], r8
        MOV  [r1 + VS_LITS], r12
        MOV  r2, [r14 + FR_METHOD]
        MOV  [r1 + VS_METHOD], r2
        RET

op_slow:                        ; a bytecode without a fast path
        LEA  r8, [r8 - 1]
slow:                           ; r8 = the bytecode for C to run
        BSR  save
        CALL _egret_step
        TST  r1, r1
        BNE  exit
reload: MOV  r1, [_egret_st]
        MOV  r10, [r1 + VS_SP]
        LEA  r10, [r10 + 4]
        MOV  r9, [r1 + VS_BP]
        MOV  r14, [r1 + VS_FP]
        MOV  r8, [r1 + VS_IP]
        MOV  r12, [r1 + VS_LITS]
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

; ---- pushes and stores ----------------------------------------------------------

op_push_nil:
        MOV  [r10]+, r11
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_push_true:
        MOV  r1, #TRUE_V
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_push_false:
        MOV  r1, #FALSE_V
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_push_self:
        MOV  r1, [r9]
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_push_bself:                  ; a block's self, from its closure
        MOV  r1, [r9]
        MOV  r1, [r1 + 8 + 4*CL_SELF]
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_push_int:
        MOV  r1, byte [r8]+
        SXB  r1
        LEA  r1, [r1 + r1 + 1]
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_push_lit:
        MOV  r1, byte [r8]+
        MOV  r1, [r12 + r1*4]
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_push_local:
        MOV  r1, byte [r8]+
        MOV  r1, [r9 + r1*4]
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_store_local:
        MOV  r1, byte [r8]+
        MOV  r2, [r10 - 4]
        MOV  [r9 + r1*4], r2
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_pop_local:
        MOV  r1, byte [r8]+
        MOV  r2, -[r10]
        MOV  [r9 + r1*4], r2
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_push_boxed:
        MOV  r1, byte [r8]+
        MOV  r1, [r9 + r1*4]
        MOV  r1, [r1 + 8]
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_store_boxed:
        MOV  r1, byte [r8]+
        MOV  r1, [r9 + r1*4]
        MOV  r2, [r10 - 4]
        MOV  [r1 + 8], r2
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_push_capt:
        MOV  r1, byte [r8]+
        MOV  r2, [r9]
        MOV  r1, [r2 + r1*4 + 8 + 4*CL_CAPT]
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_store_capt:
        MOV  r1, byte [r8]+
        MOV  r2, [r9]
        MOV  r3, [r10 - 4]
        MOV  [r2 + r1*4 + 8 + 4*CL_CAPT], r3
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_push_capt_boxed:
        MOV  r1, byte [r8]+
        MOV  r2, [r9]
        MOV  r1, [r2 + r1*4 + 8 + 4*CL_CAPT]
        MOV  r1, [r1 + 8]
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_store_capt_boxed:
        MOV  r1, byte [r8]+
        MOV  r2, [r9]
        MOV  r1, [r2 + r1*4 + 8 + 4*CL_CAPT]
        MOV  r3, [r10 - 4]
        MOV  [r1 + 8], r3
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_push_ivar:
        MOV  r1, byte [r8]+
        MOV  r2, [r9]
        MOV  r1, [r2 + r1*4 + 8]
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_store_ivar:
        MOV  r1, byte [r8]+
        MOV  r2, [r9]
        MOV  r3, [r10 - 4]
        MOV  [r2 + r1*4 + 8], r3
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_push_bivar:
        MOV  r1, byte [r8]+
        MOV  r2, [r9]
        MOV  r2, [r2 + 8 + 4*CL_SELF]
        MOV  r1, [r2 + r1*4 + 8]
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_store_bivar:
        MOV  r1, byte [r8]+
        MOV  r2, [r9]
        MOV  r2, [r2 + 8 + 4*CL_SELF]
        MOV  r3, [r10 - 4]
        MOV  [r2 + r1*4 + 8], r3
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_push_global:                 ; the literal is the global's cell
        MOV  r1, byte [r8]+
        MOV  r1, [r12 + r1*4]
        MOVS r1, [r1]
        BEQ  .undefined
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]
.undefined:
        LEA  r8, [r8 - 2]
        BRA  slow

op_store_global:
        MOV  r1, byte [r8]+
        MOV  r1, [r12 + r1*4]
        MOV  r2, [r10 - 4]
        MOV  [r1], r2
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_pop: SUB  r10, #4
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_dup: MOV  r1, [r10 - 4]
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

; ---- sends -------------------------------------------------------------------------

op_send:                        ; SEND literal argc
        MOV  r1, byte [r8]+
        MOV  r6, [r12 + r1*4]
        MOV  r7, byte [r8]+
        MOV  r5, #3
; Send selector r6 with argc r7 arguments; r5 is the length of the
; bytecode, to go back over on the slow path.
;@rcv
send:   NOT  r4, r7
        LEA  r4, [r10 + r4*4]   ; the receiver's slot: the new frame's bp
        MOV  r1, [r4]
;@end
;@classof
        RRC  r2, r1             ; a SmallInt?
        BCS  .int
        MOV  r2, [r1]           ; its class
;@end
;@hash
.probe: MOV  r3, r2             ; the cache entry: (class ^ selector) & 0xFFC
        XOR  r3, r6
        AND  r3, #0xFFC
;@end
;@probe
        CMP  r2, [r3 + _mcache_cls]
        BNE  .miss
        CMP  r6, [r3 + _mcache_sel]
        BNE  .miss
        MOV  r3, [r3 + _mcache_method]
;@end
;@arity
        CMP  r7, [r3 + 8 + 4*M_ARITY]
        BNE  .notplain
;@end
; Call Egret method r3 with its frame at r4.
;@frame
.call:  MOV  [r14 + FR_IP], r8  ; where the caller goes on
        LEA  r14, [r14 + FRAME_SIZE]
        CMP  r14, [_egret_frames_end]
        BHS  .overflow
        MOV  [r14 + FR_BP], r4
        MOV  [r14 + FR_METHOD], r3
        CLR  [r14 + FR_SERIAL]
        CLR  [r14 + FR_FLAGS]
        MOV  r9, r4
        MOVS r1, [r3 + 8 + 4*M_NLOCALS]
        BEQ  .go
;@end
;@clear
        CMP  r10, [_egret_vstack_end]
        BHS  .overflow2
.clear: MOV  [r10]+, r11
        DBNZ r1, .clear
;@end
;@enter
.go:    MOV  r12, [r3 + 8 + 4*M_LITSP]
        MOV  r8, [r3 + 8 + 4*M_CODEP]
;@end
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

;@classof
.int:   MOV  r2, [_cls_Int]
        BRA  .probe
;@end

.overflow2:
        MOV  r9, [r14 - FRAME_SIZE + FR_BP]
.overflow:
        LEA  r14, [r14 - FRAME_SIZE]
.miss:  SUB  r8, r5
        BRA  slow

.notplain:
        MOV  r1, [r3 + 8 + 4*M_ARITY]
        SUB  r1, #ARITY_PRIM
        CMP  r1, r7
        BNE  .special
        ; a C primitive: prim_table[prim](bp, argc)
;@primcall
        LEA  r1, [r10 - 4]
        MOV  [_vm_sp], r1       ; the stack's top, for the collector
        MOV  r1, [r3 + 8 + 4*M_PRIM]
        LSL  r1, #2
        MOV  r3, [r1 + _prim_table]
        MOV  r1, r4
        MOV  r2, r7
        PUSH r4
        CALL r3
        POP  r4
        TST  r1, r1
        BEQ  .failed
        MOV  [r4], r1           ; the result in place of the receiver
        LEA  r10, [r4 + 4]
;@end
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]
.failed:
        BSR  save
        CALL _egret_prim_failed
        TST  r1, r1
        BNE  exit
        BRA  reload

.special:
        CMP  r3, [_egret_blockcall]
        BNE  .new
        MOV  r1, [r4]           ; a block's call
        MOV  r3, [r1 + 8 + 4*CL_METHOD]
        CMP  r7, [r3 + 8 + 4*M_ARITY]
        BEQ  .call
        BRA  .miss
.new:   MOV  r1, [r3 + 8 + 4*M_PRIM]
        CMP  r1, #PR_NEW
        BNE  .miss
        ; new (or call) of a class of plain objects, when its init is in
        ; the cache: make the object, then call init on it, in a frame
        ; that returns the object. Nothing changes before the checks pass,
        ; so the slow path can start over.
        MOV  r1, [r4]           ; the class
        MOV  r2, [r1 + 8 + 4*C_KIND]
        CMP  r2, #1             ; K_OBJECT, as a SmallInt
        BNE  .miss
        MOV  r2, [_sym_init]
        MOV  r3, r1
        XOR  r3, r2
        AND  r3, #0xFFC
        CMP  r1, [r3 + _mcache_cls]
        BNE  .miss
        CMP  r2, [r3 + _mcache_sel]
        BNE  .miss
        MOV  r3, [r3 + _mcache_method]
        CMP  r7, [r3 + 8 + 4*M_ARITY]
        BNE  .miss
        LEA  r2, [r10 - 4]
        MOV  [_vm_sp], r2
        SAVE r3-r5              ; r5 too: .newover goes back by it
        MOV  r2, [r1 + 8 + 4*C_NIVARS]
        ASR  r2, #1
        CALL _alloc_obj
        RESTORE r3-r5
        MOV  [r4], r1           ; the object in place of the class
        MOV  [r14 + FR_IP], r8
        LEA  r14, [r14 + FRAME_SIZE]
        CMP  r14, [_egret_frames_end]
        BHS  .newover
        MOV  [r14 + FR_BP], r4
        MOV  [r14 + FR_METHOD], r3
        CLR  [r14 + FR_SERIAL]
        MOV  r1, #FR_CONSTRUCT
        MOV  [r14 + FR_FLAGS], r1
        MOV  r9, r4
        MOVS r1, [r3 + 8 + 4*M_NLOCALS]
        BEQ  .go
        CMP  r10, [_egret_vstack_end]
        BLO  .clear
        ; too deep: put the class back, and C starts the new over and
        ; raises the error
        MOV  r9, [r14 - FRAME_SIZE + FR_BP]
.newover:
        LEA  r14, [r14 - FRAME_SIZE]
        MOV  r1, [r4]
        MOV  r1, [r1]
        MOV  [r4], r1
        BRA  .miss

op_send_super:                  ; SEND_SUPER literal argc: look up from above the method's owner
        MOV  r1, byte [r8]+
        MOV  r6, [r12 + r1*4]
        MOV  r7, byte [r8]+
        MOV  r5, #3
        NOT  r4, r7
        LEA  r4, [r10 + r4*4]
        MOV  r2, [r14 + FR_METHOD]
        MOV  r2, [r2 + 8 + 4*M_OWNER]
        MOV  r2, [r2 + 8 + 4*C_SUPER]
        CMP  r2, r11            ; no superclass: C says so
        BNE  send.probe
        SUB  r8, r5
        BRA  slow

op_return:
;@retcheck
        MOV  r1, -[r10]
        MOVS r2, [r14 + FR_FLAGS]
        BNE  .flags
;@end
;@ret
.ret:   MOV  [r9], r1           ; the result in the receiver's slot
        LEA  r10, [r9 + 4]
        LEA  r14, [r14 - FRAME_SIZE]
        MOV  r9, [r14 + FR_BP]
        MOV  r2, [r14 + FR_METHOD]
        MOV  r12, [r2 + 8 + 4*M_LITSP]
        MOV  r8, [r14 + FR_IP]
;@end
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]
.flags: CMP  r2, #FR_CONSTRUCT  ; new: the receiver, not init's result
        BNE  .slowret
        MOV  r1, [r9]
        BRA  .ret
.slowret:
        ADD  r10, #4
        LEA  r8, [r8 - 1]
        BRA  slow

; ---- arithmetic: SmallInts here, anything else a send -------------------------

; binary operators that can't take the fast path: send the operator
binop_slow:
        ADD  r10, #8
        MOV  r1, byte [r8 - 1]
        LSL  r1, #2
        MOV  r6, [r1 + _egret_special]
        MOV  r7, #1
        MOV  r5, #1
        BRA  send

op_add: MOV  r2, -[r10]         ; b
        MOV  r1, -[r10]         ; a
;@tag2
        MOV  r3, r1
        AND  r3, r2
        AND  r3, #1
        BEQ  binop_slow
;@end
;@tagadd
        DEC  r2                 ; (2x + 1) + 2y, overflow in V
        ADD  r1, r2
        BVS  binop_slow
;@end
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_sub: MOV  r2, -[r10]
        MOV  r1, -[r10]
;@tag2
        MOV  r3, r1
        AND  r3, r2
        AND  r3, #1
        BEQ  binop_slow
;@end
;@tagsub
        DEC  r2
        SUB  r1, r2
        BVS  binop_slow
;@end
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_mul: MOV  r2, -[r10]
        MOV  r1, -[r10]
;@tag2
        MOV  r3, r1
        AND  r3, r2
        AND  r3, #1
        BEQ  binop_slow
;@end
;@tagmul
        ASR  r1, #1             ; x * 2y, too big for 32 bits in V
        DEC  r2
        MULS r1, r2
        BVS  binop_slow
        INC  r1
;@end
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_div: MOV  r2, -[r10]
        MOV  r1, -[r10]
;@tag2
        MOV  r3, r1
        AND  r3, r2
        AND  r3, #1
        BEQ  binop_slow
;@end
        CMP  r2, #1             ; by 0
        BEQ  binop_slow
        CMP  r2, #-1            ; by -1: -2^30 / -1 is too big
        BEQ  binop_slow
        ASR  r1, #1
        ASR  r2, #1
        DIVS r1, r2
        MOV  r3, r0             ; floor: one less if the remainder and
        TST  r3, r3             ; the divisor have different signs
        BEQ  .exact
        XOR  r3, r2
        BPL  .exact
        DEC  r1
.exact: LEA  r1, [r1 + r1 + 1]
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_mod: MOV  r2, -[r10]
        MOV  r1, -[r10]
;@tag2
        MOV  r3, r1
        AND  r3, r2
        AND  r3, #1
        BEQ  binop_slow
;@end
        CMP  r2, #1
        BEQ  binop_slow
        CMP  r2, #-1
        BEQ  binop_slow
        ASR  r1, #1
        ASR  r2, #1
        DIVS r1, r2
        MOV  r1, r0             ; floor: the remainder takes the
        TST  r1, r1             ; divisor's sign
        BEQ  .done
        MOV  r3, r1
        XOR  r3, r2
        BPL  .done
        ADD  r1, r2
.done:  LEA  r1, [r1 + r1 + 1]
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

; the comparisons: SmallInts compare as they are
op_lt:  MOV  r2, -[r10]
        MOV  r1, -[r10]
;@tag2
        MOV  r3, r1
        AND  r3, r2
        AND  r3, #1
        BEQ  binop_slow
;@end
;@cmpbr
        CMP  r1, r2
        BGE  push_false
;@end
push_true:
        MOV  r1, #TRUE_V
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]
push_false:
        MOV  r1, #FALSE_V
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_le:  MOV  r2, -[r10]
        MOV  r1, -[r10]
;@tag2
        MOV  r3, r1
        AND  r3, r2
        AND  r3, #1
        BEQ  binop_slow
;@end
;@cmpbr
        CMP  r1, r2
        BGT  push_false
;@end
        BRA  push_true

op_gt:  MOV  r2, -[r10]
        MOV  r1, -[r10]
;@tag2
        MOV  r3, r1
        AND  r3, r2
        AND  r3, #1
        BEQ  binop_slow
;@end
;@cmpbr
        CMP  r1, r2
        BLE  push_false
;@end
        BRA  push_true

op_ge:  MOV  r2, -[r10]
        MOV  r1, -[r10]
;@tag2
        MOV  r3, r1
        AND  r3, r2
        AND  r3, #1
        BEQ  binop_slow
;@end
;@cmpbr
        CMP  r1, r2
        BLT  push_false
;@end
        BRA  push_true

op_eq:  MOV  r2, -[r10]
        MOV  r1, -[r10]
        CMP  r1, r2
        BEQ  push_true
        MOV  r3, r1             ; a SmallInt and something else: unequal
        OR   r3, r2
        AND  r3, #1
        BNE  push_false
        LEA  r3, [r1 - FALSE_V] ; nil, true or false: equal only to themselves
        CMP  r3, #TRUE_V - FALSE_V
        BLS  push_false
        LEA  r3, [r2 - FALSE_V]
        CMP  r3, #TRUE_V - FALSE_V
        BLS  push_false
        BRA  binop_slow

op_band:
        MOV  r2, -[r10]
        MOV  r1, -[r10]
;@tag2
        MOV  r3, r1
        AND  r3, r2
        AND  r3, #1
        BEQ  binop_slow
;@end
        AND  r1, r2
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_bor: MOV  r2, -[r10]
        MOV  r1, -[r10]
;@tag2
        MOV  r3, r1
        AND  r3, r2
        AND  r3, #1
        BEQ  binop_slow
;@end
        OR   r1, r2
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_bxor:
        MOV  r2, -[r10]
        MOV  r1, -[r10]
;@tag2
        MOV  r3, r1
        AND  r3, r2
        AND  r3, #1
        BEQ  binop_slow
;@end
        XOR  r1, r2
        OR   r1, #1
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_shl: MOV  r2, -[r10]
        MOV  r1, -[r10]
;@tag2
        MOV  r3, r1
        AND  r3, r2
        AND  r3, #1
        BEQ  binop_slow
;@end
        ASR  r2, #1             ; the count, 0 to 30 here
        CMP  r2, #30
        BHI  binop_slow
        DEC  r1                 ; 2x << n, if shifting back gives 2x
        MOV  r3, r1
        LSL  r3, r2
        MOV  r4, r3
        ASR  r4, r2
        CMP  r4, r1
        BNE  binop_slow
        INC  r3
        MOV  [r10]+, r3
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_shr: MOV  r2, -[r10]
        MOV  r1, -[r10]
;@tag2
        MOV  r3, r1
        AND  r3, r2
        AND  r3, #1
        BEQ  binop_slow
;@end
        ASR  r2, #1
        CMP  r2, #31
        BHI  binop_slow
        ASR  r1, r2             ; (2x + 1) >> n has 2(x >> n) above bit 0
        OR   r1, #1
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_at:  MOV  r2, -[r10]         ; the index
        MOV  r1, -[r10]         ; the List
        RRC  r3, r2
        BCC  binop_slow
        RRC  r3, r1
        BCS  binop_slow
        MOV  r3, [r1]
        CMP  r3, [_cls_List]
        BNE  binop_slow
        CMP  r2, [r1 + 8 + 4*L_SIZE]    ; unsigned: a negative index fails too
        BHS  binop_slow
        MOV  r3, [r1 + 8 + 4*L_ITEMS]
        ASR  r2, #1
        MOV  r1, [r3 + r2*4 + 8]
        MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_at_put:
        MOV  r4, -[r10]         ; the value
        MOV  r2, -[r10]         ; the index
        MOV  r1, -[r10]         ; the List
        RRC  r3, r2
        BCC  .slow
        RRC  r3, r1
        BCS  .slow
        MOV  r3, [r1]
        CMP  r3, [_cls_List]
        BNE  .slow
        CMP  r2, [r1 + 8 + 4*L_SIZE]
        BHS  .slow
        MOV  r3, [r1 + 8 + 4*L_ITEMS]
        ASR  r2, #1
        MOV  [r3 + r2*4 + 8], r4
        MOV  [r10]+, r4
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]
.slow:  ADD  r10, #12
        MOV  r6, [_egret_special + 4*OP_AT_PUT]
        MOV  r7, #2
        MOV  r5, #1
        BRA  send

op_not: MOV  r1, -[r10]
        OR   r1, #8             ; nil or false
        CMP  r1, r11
        BEQ  push_true
        BRA  push_false

; ---- jumps ---------------------------------------------------------------------

op_jump:                        ; a signed 16-bit offset, little-endian
;@jumpoff
        MOV  r1, byte [r8 + 1]
        SXB  r1
        LSL  r1, #8
        OR   r1, byte [r8]
        LEA  r8, [r8 + r1 + 2]
;@end
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_jump_false:
        MOV  r1, -[r10]
;@truthy
        OR   r1, #8
        CMP  r1, r11
;@end
        BEQ  op_jump
        LEA  r8, [r8 + 2]
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_jump_true:
        MOV  r1, -[r10]
;@truthy
        OR   r1, #8
        CMP  r1, r11
;@end
        BNE  op_jump
        LEA  r8, [r8 + 2]
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_jump_false_or_pop:
        MOV  r1, [r10 - 4]
;@truthy
        OR   r1, #8
        CMP  r1, r11
;@end
        BEQ  op_jump
        SUB  r10, #4
        LEA  r8, [r8 + 2]
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_jump_true_or_pop:
        MOV  r1, [r10 - 4]
;@truthy
        OR   r1, #8
        CMP  r1, r11
;@end
        BNE  op_jump
        SUB  r10, #4
        LEA  r8, [r8 + 2]
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

; ---- loops ---------------------------------------------------------------------

op_range_next:                  ; RANGE_NEXT slot exit: slot = counter, slot + 1 = last
        MOV  r1, byte [r8]+
        LEA  r1, [r9 + r1*4]
        MOV  r2, [r1]
        ADD  r2, #2
        CMP  r2, [r1 + 4]
        BGT  op_jump
        MOV  [r1], r2
        MOV  [r10]+, r2
        LEA  r8, [r8 + 2]
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_iter_next:                   ; ITER_NEXT slot exit: slot = a List or a Range
        MOV  r1, byte [r8]+
        LEA  r1, [r9 + r1*4]
        MOV  r2, [r1]
        MOV  r3, [r2]
        CMP  r3, [_cls_List]
        BNE  .range
        MOV  r3, [r1 + 4]       ; the index, as a SmallInt
        CMP  r3, [r2 + 8 + 4*L_SIZE]
        BGE  op_jump
        MOV  r4, [r2 + 8 + 4*L_ITEMS]
        MOV  r5, r3
        ASR  r5, #1
        MOV  r5, [r4 + r5*4 + 8]
        MOV  [r10]+, r5
        ADD  r3, #2
        MOV  [r1 + 4], r3
        LEA  r8, [r8 + 2]
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]
.range: MOV  r3, [r1 + 4]
        ADD  r3, #2
        CMP  r3, [r2 + 8 + 4*R_LAST]
        BGT  op_jump
        MOV  [r1 + 4], r3
        MOV  [r10]+, r3
        LEA  r8, [r8 + 2]
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

op_inc_local:                   ; INC_LOCAL slot step, then 7 bytes of general code
        MOV  r1, byte [r8]+
        MOV  r2, byte [r8]+
        SXB  r2
        LEA  r3, [r9 + r1*4]
        MOV  r1, [r3]
        RRC  r4, r1
        BCC  .general
        ADD  r2, r2
        ADD  r1, r2
        BVS  .general
        MOV  [r3], r1
        LEA  r8, [r8 + 7]
.general:
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]

; ---- closures --------------------------------------------------------------------

op_closure:                     ; CLOSURE method n (kind index)*n
        LEA  r1, [r10 - 4]
        MOV  [_vm_sp], r1
        MOV  r1, [_cls_Block]
        MOV  r2, byte [r8 + 1]
        ADD  r2, #CL_CAPT
        CALL _alloc_obj         ; the closure, in r1
        MOV  r2, byte [r8]+
        MOV  r2, [r12 + r2*4]
        MOV  [r1 + 8 + 4*CL_METHOD], r2
        MOV  r4, [r9]
        MOV  r3, [r14 + FR_METHOD]
        MOV  r3, [r3 + 8 + 4*M_INFO]
        AND  r3, #MF_BLOCK
        BNE  .inblock
        MOV  [r1 + 8 + 4*CL_SELF], r4
        MOV  [r1 + 8 + 4*CL_HOME], r14
        MOVS r3, [r14 + FR_SERIAL]      ; this frame's serial, made now if
        BNE  .serial                    ; it has none yet
        MOV  r3, [_egret_serial]
        ADD  r3, #2
        MOV  [_egret_serial], r3
        MOV  [r14 + FR_SERIAL], r3
.serial:
        MOV  [r1 + 8 + 4*CL_SERIAL], r3
        BRA  .capts
.inblock:                               ; a block in a block: the same self and home
        MOV  r3, [r4 + 8 + 4*CL_SELF]
        MOV  [r1 + 8 + 4*CL_SELF], r3
        MOV  r3, [r4 + 8 + 4*CL_HOME]
        MOV  [r1 + 8 + 4*CL_HOME], r3
        MOV  r3, [r4 + 8 + 4*CL_SERIAL]
        MOV  [r1 + 8 + 4*CL_SERIAL], r3
.capts: MOVS r2, byte [r8]+
        BEQ  .done
        LEA  r3, [r1 + 8 + 4*CL_CAPT]
.loop:  MOVS r4, byte [r8]+     ; CK_LOCAL (0) or CK_CAPT
        MOV  r5, byte [r8]+     ; (MOV leaves the flags alone)
        BNE  .capt
        MOV  r4, [r9 + r5*4]
        BRA  .put
.capt:  MOV  r4, [r9]
        MOV  r4, [r4 + r5*4 + 8 + 4*CL_CAPT]
.put:   MOV  [r3]+, r4
        DBNZ r2, .loop
.done:  MOV  [r10]+, r1
        MOV  r1, byte [r8]+
        JMP  [r13 + r1*4]
