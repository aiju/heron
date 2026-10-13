; The glue between Egret's native code (vm/jit.c) and the C side. As
; interp_v1b.s, it gets the C headers' constants from build.py.
;
; The native code keeps some of the interpreter's registers (interp_v1b.s):
; r9 bp, r10 the value stack's next free slot, r11 the frame, r14 nil, and
; r8 the bytecode's address when C needs it. It doesn't keep r12, the
; literals: the glue finds them (jsave) before it goes to C.

        .global _jit_run, _jit_glue_slow, _jit_glue_send_miss, _jit_glue_prim_failed
        .global _jit_glue_gsend_miss, _jit_glue_redo

        .section .text.egret_jit

; int jit_run(VMState *st): carry on in native code from st, until the
; first frame returns (STEP_RETURNED) or an error nobody catches ends it
; (STEP_ERROR).
_jit_run:
        SAVE r8-r14
        MOV  r2, [_egret_st]
        PUSH r2
        ST   r1, [_egret_st]
        MOV  r14, #NIL
        BRA  resume

jexit:  POP  r2
        ST   r2, [_egret_st]
        RESTORE r8-r14
        RET

; The registers from egret_st, then on in the native code for its frame's
; method at its bytecode (jit_resume compiles the method if it has to).
resume: MOV  r1, [_egret_st]
        MOV  r10, [r1 + VS_SP]
        LEA  r10, [r10 + 4]
        MOV  r9, [r1 + VS_BP]
        MOV  r11, [r1 + VS_FP]
        MOV  r8, [r1 + VS_IP]
        MOV  r12, [r1 + VS_LITS]
        CALL _jit_resume
        JMP  r1

; The registers into egret_st, as the asm loop's save does, with r12 the
; frame's method's literals.
jsave:  MOV  r12, [r11 + FR_METHOD]
        MOV  r12, [r12 + 8 + 4*M_LITSP]
        BRA  _egret_save

; C runs the bytecode at r8.
_jit_glue_slow:
        BSR  jsave
        CALL _egret_step
        TST  r1, r1
        BNE  jexit
        BRA  resume

; A send's inline cache missed: r8 is the send's bytecode (a SEND, or an
; operator's), r6 the site's number. jit_send_miss binds the site and says
; where it starts, to run it again; or C runs the bytecode.
_jit_glue_send_miss:
        BSR  jsave
        MOV  r2, r6
        CALL _jit_send_miss
        TST  r1, r1
        BEQ  .generic
        JMP  r1
.generic:
        MOV  r1, [_egret_st]
        CALL _egret_step
        TST  r1, r1
        BNE  jexit
        BRA  resume

; A send through the method cache (gsend in jit.c) missed it, or found a
; method not yet compiled: r7 is the send's bytecode, r8 the one after,
; the return address of the send on the stack. jit_gsend_miss fills the
; cache and says what to call (and its bp); or C makes the send.
_jit_glue_gsend_miss:
        BSR  jsave
        MOV  r2, r7
        CALL _jit_gsend_miss
        TST  r1, r1
        BEQ  .gslow
        MOV  r4, [_jit_bp]
        JMP  r1
.gslow: POP  r1
        MOV  r1, [_egret_st]
        CALL _egret_step
        TST  r1, r1
        BNE  jexit
        BRA  resume

; A send native code can't make (r8 is the bytecode after it): C backs up
; to it and makes it.
_jit_glue_redo:
        BSR  jsave
        CALL _jit_back_up
        MOV  r1, [_egret_st]
        CALL _egret_step
        TST  r1, r1
        BNE  jexit
        BRA  resume

; A primitive failed (its stub has dropped its return address): raise its
; error. r8 is the bytecode after the send.
_jit_glue_prim_failed:
        BSR  jsave
        CALL _egret_prim_failed
        TST  r1, r1
        BNE  jexit
        BRA  resume
