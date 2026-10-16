; The Fen kernel's entry and exit, and the helpers C can't write.
;
; The kernel runs in supervisor mode in bank 0 with interrupts off, on one
; stack, kstack. Coming from user mode, the exception's frame (sr, then
; the PC above it) is always at the top of that stack, kstack_top - 8, and
; the kernel returns with RTI from there: switching threads is rewriting
; the frame and setting bank and ctx (proc.c, schedule). Nothing of a
; user thread is saved: its registers are in its own bank. On the way out
; (kexit) the kernel reschedules if something asked for it.
;
; Only two things happen in supervisor mode with the kernel interrupted:
; an interrupt while it waits in idle_wait, which keeps r7 and needs
; nothing else, and a page fault in a copy of user memory (ucopy,
; ustrncpy), which resumes at the copy's fault exit. Anything else is a
; bug, and panics.
;
; The SWI vectors and the system calls' stubs are generated from
; syscalls.py (build/fen/gen/ksys.s).

        .far _kmain, _exception, _interrupt, _schedule, _need_resched
        .far _kernel_fault, _copy_fault, kstack_top, ufault_start, ufault_end, ufault
        .global kexit, kstack_top
        .global _idle_wait, _map_get, _map_set, _map_clear, _set_bank, _get_bank
        .global _set_ctx, _get_ctx, _get_sr, _ureg_set, _ureg_get, _bank_copy, _page_zero
        .global _bank_copy_ur, _bank_msg, _bank_msg_ur
        .global _ucopy, _ustrncpy, _clz, _halt, _start_first, _get_far, _get_fsr

; ---- the exception vectors (RFC 0029, 6), 4 bytes each

        .org 0x80000000
        JMP  reset
        .org 0x80000004
        JMP  exc_nmi
        .org 0x80000008
        JMP  exc_illegal
        .org 0x8000000C
        JMP  exc_bus
        .org 0x80000010
        JMP  exc_div
        .org 0x80000014
        JMP  exc_addr
        .org 0x80000018
        JMP  exc_tag
        .org 0x8000001C
        JMP  exc_priv
        .org 0x80000020
        JMP  exc_page
        .org 0x80000024
        JMP  exc_trace
        .org 0x80000040
        JMP  irq0
        JMP  irq1
        JMP  irq2
        JMP  irq3
        JMP  irq4
        JMP  irq5
        JMP  irq6
        JMP  irq7

        .section .text.entry

reset:  MOV  sp, #kstack_top
        CALL _kmain
        BRA  _halt

; ---- exceptions: r1 the vector's offset, then the common part

exc_nmi:
        PUSH r1
        MOV  r1, #0x04
        BRA  exc_common
exc_illegal:
        PUSH r1
        MOV  r1, #0x08
        BRA  exc_common
exc_bus:
        PUSH r1
        MOV  r1, #0x0C
        BRA  exc_common
exc_div:
        PUSH r1
        MOV  r1, #0x10
        BRA  exc_common
exc_addr:
        PUSH r1
        MOV  r1, #0x14
        BRA  exc_common
exc_tag:
        PUSH r1
        MOV  r1, #0x18
        BRA  exc_common
exc_priv:
        PUSH r1
        MOV  r1, #0x1C
        BRA  exc_common
exc_page:
        PUSH r1
        MOV  r1, #0x20
        BRA  exc_common
exc_trace:
        PUSH r1
        MOV  r1, #0x24

; [sp] the interrupted r1, [sp + 4] its sr, [sp + 8] its PC
exc_common:
        PUSH r2
        MOVS r2, [sp + 8]               ; the sr it came from: S is the sign
        BMI  .kernel
        ADD  sp, #8                     ; the frame, at the top of the stack
        CALL _exception                 ; exception(vector)
        JMP  kexit
; in the kernel: a page fault in a copy of user memory is the user's
; stack growing (copy_fault maps the page, and the copy goes on), or it
; resumes at the copy's fault exit; anything else is a bug
.kernel:
        CMP  r1, #0x20
        BNE  .bug
        MOV  r2, [sp + 12]              ; the faulting PC
        CMP  r2, #ufault_start
        BLO  .bug
        CMP  r2, #ufault_end
        BHS  .bug
        SAVE r0-r7                      ; the copy's registers, and C's scratch
        CALL _copy_fault
        CMP  r1, #0
        RESTORE r0-r7
        BNE  .again
        MOV  r2, #ufault
        MOV  [sp + 12], r2
.again: POP  r2
        POP  r1
        RTI
.bug:   LEA  r2, [sp + 8]               ; the frame
        CALL _kernel_fault              ; kernel_fault(vector, frame): panics

; ---- interrupts: r1 the level

irq0:   PUSH r1
        MOV  r1, #0
        BRA  irq_common
irq1:   PUSH r1
        MOV  r1, #1
        BRA  irq_common
irq2:   PUSH r1
        MOV  r1, #2
        BRA  irq_common
irq3:   PUSH r1
        MOV  r1, #3
        BRA  irq_common
irq4:   PUSH r1
        MOV  r1, #4
        BRA  irq_common
irq5:   PUSH r1
        MOV  r1, #5
        BRA  irq_common
irq6:   PUSH r1
        MOV  r1, #6
        BRA  irq_common
irq7:   PUSH r1
        MOV  r1, #7

; from user mode, or from idle_wait, where only r7 is live and it keeps
; that itself: either way the handler may use every register
irq_common:
        ADD  sp, #4                     ; the frame
        MOVS r2, [sp]                   ; the sr it came from
        BMI  .idle
        CALL _interrupt                 ; interrupt(level)
        JMP  kexit
.idle:  CALL _interrupt
        RTI

; ---- back to user mode

kexit:  MOVS r1, [_need_resched]
        BNE  .switch
        RTI
.switch:
        CALL _schedule
        RTI

; the first thread: schedule writes its frame
_start_first:
        MOV  sp, #kstack_top - 8
        CALL _schedule
        RTI

; wait for an interrupt with interrupts on, from the scheduler's idle loop
_idle_wait:
        PUSH r7
        EI
        HALT
        DI
        POP  r7
        RET

_halt:  DI
        HALT
        BRA  _halt

; ---- special registers

; map_get(index): the map entry at mapa = index
_map_get:
        MTSR mapa, r1
        MFSR r1, mapd
        RET

; map_set(index, entry)
_map_set:
        MTSR mapa, r1
        MTSR mapd, r2
        RET

; map_clear(first, n): n > 0 entries from first made invalid
_map_clear:
        MTSR mapa, r1
        CLR  r3
.clr:   MTSR mapd, r3
        DBNZ r2, .clr
        RET

_set_bank:
        MTSR bank, r1
        RET
_get_bank:
        MFSR r1, bank
        RET
_set_ctx:
        MTSR ctx, r1
        RET
_get_ctx:
        MFSR r1, ctx
        RET
_get_sr:
        MFSR r1, sr
        RET
_get_far:
        MFSR r1, far
        RET
_get_fsr:
        MFSR r1, fsr
        RET

; page_zero(p): a page of zeros, sixteen bytes a store
_page_zero:
        SAVE r8-r12
        MOV  r8, #0
        MOV  r9, #0
        MOV  r10, #0
        MOV  r11, #0
        MOV  r12, #16
        MOV  r0, #64
.pz:    STM  r1, r8-r11
        ADD  r1, r12
        STM  r1, r8-r11
        ADD  r1, r12
        STM  r1, r8-r11
        ADD  r1, r12
        STM  r1, r8-r11
        ADD  r1, r12
        DBNZ r0, .pz
        RESTORE r8-r12
        RET

; bank_copy(to, from): r0-r7 of bank `from` into bank `to`
_bank_copy:
        BCOPY r1, r2
        RET

; bank_msg(to, from, a, b): a message: bank_copy, and a and b into r8 and
; r9 of bank `to` (its rcvid and sender, or the reply's status)
_bank_msg:
        BCOPY r1, r2
        MFSR r0, bank
        MTSR bank, r1
        MTUR r8, r3
        MTUR r9, r4
        MTSR bank, r0
        RET

; bank_msg_ur(to, from, a, b): bank_msg with bank_copy_ur
_bank_msg_ur:
        SAVE r3-r7
        CALL _bank_copy_ur
        RESTORE r3-r7
        MFSR r0, bank
        MTSR bank, r1
        MTUR r8, r3
        MTUR r9, r4
        MTSR bank, r0
        RET

; bank_copy_ur(to, from): the same without BCOPY, through the kernel's
; registers with MFUR and MTUR (to compare; ipc.c uses it with COPY_UR)
_bank_copy_ur:
        SAVE r8-r11
        MFSR r0, bank
        MTSR bank, r2
        MFUR r3, r0
        MFUR r4, r1
        MFUR r5, r2
        MFUR r6, r3
        MFUR r8, r4
        MFUR r9, r5
        MFUR r10, r6
        MFUR r11, r7
        MTSR bank, r1
        MTUR r0, r3
        MTUR r1, r4
        MTUR r2, r5
        MTUR r3, r6
        MTUR r4, r8
        MTUR r5, r9
        MTUR r6, r10
        MTUR r7, r11
        MTSR bank, r0
        RESTORE r8-r11
        RET

; ureg_set(bank, n, v): register n of a bank <- v
_ureg_set:
        MFSR r4, bank
        MTSR bank, r1
        LSL  r2, #2
        LEA  r5, [pc + .set0]
        ADD  r5, r2
        JMP  r5
.set0:  MTUR r0, r3
        BRA  .sdone
        MTUR r1, r3
        BRA  .sdone
        MTUR r2, r3
        BRA  .sdone
        MTUR r3, r3
        BRA  .sdone
        MTUR r4, r3
        BRA  .sdone
        MTUR r5, r3
        BRA  .sdone
        MTUR r6, r3
        BRA  .sdone
        MTUR r7, r3
        BRA  .sdone
        MTUR r8, r3
        BRA  .sdone
        MTUR r9, r3
        BRA  .sdone
        MTUR r10, r3
        BRA  .sdone
        MTUR r11, r3
        BRA  .sdone
        MTUR r12, r3
        BRA  .sdone
        MTUR r13, r3
        BRA  .sdone
        MTUR r14, r3
        BRA  .sdone
        MTUR r15, r3
.sdone: MTSR bank, r4
        RET

; ureg_get(bank, n): register n of a bank
_ureg_get:
        MFSR r4, bank
        MTSR bank, r1
        LSL  r2, #2
        LEA  r5, [pc + .get0]
        ADD  r5, r2
        JMP  r5
.get0:  MFUR r1, r0
        BRA  .gdone
        MFUR r1, r1
        BRA  .gdone
        MFUR r1, r2
        BRA  .gdone
        MFUR r1, r3
        BRA  .gdone
        MFUR r1, r4
        BRA  .gdone
        MFUR r1, r5
        BRA  .gdone
        MFUR r1, r6
        BRA  .gdone
        MFUR r1, r7
        BRA  .gdone
        MFUR r1, r8
        BRA  .gdone
        MFUR r1, r9
        BRA  .gdone
        MFUR r1, r10
        BRA  .gdone
        MFUR r1, r11
        BRA  .gdone
        MFUR r1, r12
        BRA  .gdone
        MFUR r1, r13
        BRA  .gdone
        MFUR r1, r14
        BRA  .gdone
        MFUR r1, r15
.gdone: MTSR bank, r4
        RET

_clz:   CLZ  r1, r1
        RET

; ---- copies that may fault: a page fault in [ufault_start, ufault_end)
; resumes at ufault, which returns -EFAULT. Both save r8-r11 first, and
; nothing else, so ufault knows what to put back.

; ucopy(dst, src, n): 0, or -EFAULT
_ucopy:
ufault_start:
        SAVE r8-r11
        MOV  r0, r1
        OR   r0, r2
        TST  r0, #3
        BNE  .ubytes
        CMP  r3, #16
        BLO  .uwords
.u16:   LDM  r2, r8-r11
        STM  r1, r8-r11
        ADD  r2, #16
        ADD  r1, #16
        SUB  r3, #16
        CMP  r3, #16
        BHS  .u16
.uwords:
        CMP  r3, #4
        BLO  .ubytes
.u4:    MOV  r0, [r2]+
        MOV  [r1]+, r0
        SUB  r3, #4
        CMP  r3, #4
        BHS  .u4
.ubytes:
        CMP  r3, #0
        BEQ  .udone
.u1:    MOV  r0, byte [r2]+
        MOV  byte [r1], r0
        ADD  r1, #1
        DBNZ r3, .u1
.udone: RESTORE r8-r11
        CLR  r1
        RET

; ustrncpy(dst, src, n): copy a string of at most n - 1 characters and its
; NUL; its length, or -EFAULT, or -ENAMETOOLONG if it's longer
_ustrncpy:
        SAVE r8-r11
        MOV  r8, r1
        CMP  r3, #0
        BEQ  .long
.s1:    MOVS r0, byte [r2]+
        MOV  byte [r1], r0
        BEQ  .sdone2
        ADD  r1, #1
        DBNZ r3, .s1
.long:  RESTORE r8-r11
        MOV  r1, #-36
        RET
.sdone2:
        SUB  r1, r8
        RESTORE r8-r11
        RET
ufault_end:
ufault: RESTORE r8-r11
        MOV  r1, #-14
        RET

; ---- the kernel's stack

        .section .farbss.kstack
        .align 4
kstack: .space 8192
kstack_top:
