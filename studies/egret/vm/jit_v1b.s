; The glue between Egret's native code (vm/jit.c) and the C side. As
; interp_v1b.s, it gets the C headers' constants from build.py.
;
; The native code keeps the interpreter's registers (interp_v1b.s): r9 bp,
; r10 the value stack's next free slot, r11 the frame, r12 the literals,
; r14 nil, and r8 the bytecode's address when C needs it.

        .global _jit_run, _jit_glue_slow, _jit_glue_send_miss, _jit_glue_prim_failed

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

; C runs the bytecode at r8.
_jit_glue_slow:
        BSR  _egret_save
        CALL _egret_step
        TST  r1, r1
        BNE  jexit
        BRA  resume

; A send's inline cache missed: r8 is the bytecode after the SEND, r6 the
; site's number. jit_send_miss binds the site and says where it starts, to
; run it again; or C makes the send.
_jit_glue_send_miss:
        LEA  r8, [r8 - 3]
        BSR  _egret_save
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

; A primitive failed (its stub has dropped its return address): raise its
; error. r8 is the bytecode after the send.
_jit_glue_prim_failed:
        BSR  _egret_save
        CALL _egret_prim_failed
        TST  r1, r1
        BNE  jexit
        BRA  resume
