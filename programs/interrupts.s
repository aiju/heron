; interrupts: a timer interrupt counts ticks while the main program does
; interruptible work, then sleeps with HALT for exact numbers of ticks.
; Also a software trap (SWI) used as a system call.
;
; Nothing printed depends on how many cycles anything takes: only on the
; results of the work and on tick differences measured race-free.

; Own vector table: lib/start.s has RTI at the IRQ vector.
        .org 0x0000
        JMP  start              ; reset
        .org 0x0004
        JMP  isr                ; IRQ
        .org 0x0008
        JMP  trap               ; SWI and illegal instructions

TIMER_PERIOD = 0xFF04
TIMER_FLAG   = 0xFF06
PERIOD       = 1000             ; cycles between ticks

start:  LI   sp, #0xFF00
        CALL main
        HALT

; ---- interrupt and trap handlers ----

; isr: count a tick. The CPU saves PC and the flags; the handler saves the
; registers it uses and must acknowledge the timer, or the level-triggered
; IRQ would fire again straight after RTI.
isr:    PUSH r1
        LD   r1, [ticks]
        INC  r1
        ST   r1, [ticks]
        ST   r0, [TIMER_FLAG]   ; any write acknowledges
        POP  r1
        RTI

; trap: SWI and illegal instructions share this vector, so look at the
; instruction before the saved PC to tell them apart. SWI is a system call
; that prints the string at r1.
trap:   PUSH r1
        PUSH r2
        PUSH r3
        PUSH r4
        PUSH r5
        PUSH r6
        PUSH r7
        LD   r2, [sp + 16]      ; saved PC (above 7 registers and the flags)
        LD   r2, [r2 - 2]       ; the trapping instruction (a negative offset:
        CMP  r2, #0x000C        ; long form)
        BNE  .fatal
        CALL puts               ; r1 is still the caller's r1
        POP  r7
        POP  r6
        POP  r5
        POP  r4
        POP  r3
        POP  r2
        POP  r1
        RTI
.fatal: LI   r1, #s_fatal
        CALL puts
        HALT                    ; interrupts are off in a trap: really stops

; ---- main ----

main:   PUSH r8
        PUSH r9
        PUSH r10
        LI   r1, #s_title
        CALL puts

        ST   r0, [ticks]
        LI   r1, #PERIOD
        ST   r1, [TIMER_PERIOD]
        EI

        ; Work with interrupts firing: sum of i*i for i = 1..1000. umul16
        ; keeps intermediate values in registers and the carry flag, so a
        ; handler that clobbered either would show up in the result.
        MVI  r8, 0              ; r9:r8 = sum
        MVI  r9, 0
        MVI  r10, 1
.sq:    MOV  r1, r10
        MOV  r2, r10
        CALL umul16
        ADD  r8, r1
        ADC  r9, r2
        INC  r10
        CMP  r10, #1001
        BNE  .sq
        LD   r10, [ticks]       ; ticks during the work (not printed: timing)
        LI   r1, #s_sum
        CALL puts
        MOV  r1, r8
        MOV  r2, r9
        CALL print_u32
        CALL newline
        LI   r1, #s_during
        CALL puts
        LI   r1, #s_yes
        TST  r10, r10
        BNE  .some
        LI   r1, #s_no
.some:  CALL puts

        ; sleep for exact numbers of ticks
        MVI  r1, 10
        BSR  timed_sleep
        MVI  r1, 25
        BSR  timed_sleep

        ; stop the timer: no more ticks
        DI
        ST   r0, [TIMER_PERIOD]
        ST   r0, [TIMER_FLAG]
        EI
        LD   r8, [ticks]
        LI   r9, #5000          ; idle a while with interrupts enabled
.idle:  DEC  r9
        BNE  .idle
        LI   r1, #s_stopped
        CALL puts
        LD   r1, [ticks]
        LI   r2, #s_yes
        CMP  r1, r8
        BEQ  .same
        LI   r2, #s_no
.same:  MOV  r1, r2
        CALL puts

        LI   r1, #s_syscall     ; a system call
        SWI
        DI
        LI   r1, #s_done
        CALL puts
        POP  r10
        POP  r9
        POP  r8
        RET

; timed_sleep: r1 = ticks. Sleep, then print "sleep N: M ticks" where M is
; measured around the sleep (with interrupts off at both ends, so it's exact).
timed_sleep:
        PUSH r8
        PUSH r9
        MOV  r8, r1
        DI
        LD   r9, [ticks]
        BSR  sleep
        LD   r1, [ticks]
        EI
        SUB  r1, r9
        MOV  r9, r1
        LI   r1, #s_sleep
        CALL puts
        MOV  r1, r8
        CALL print_u16
        LI   r1, #s_colon
        CALL puts
        MOV  r1, r9
        CALL print_u16
        LI   r1, #s_ticks
        CALL puts
        POP  r9
        POP  r8
        RET

; sleep: wait until r1 more ticks have been counted. Call with interrupts
; disabled; returns with them disabled. The test and the HALT must not be
; separated by a tick, or HALT would sleep through it: so the test runs with
; interrupts off, and EI; HALT is used because an interrupt can't be taken
; right after EI, only once HALT is waiting.
sleep:  LD   r2, [ticks]
        ADD  r1, r2             ; r1 = the tick count to wait for
.wait:  LD   r2, [ticks]
        CMP  r2, r1
        BHS  .done
        EI
        HALT                    ; wait for the next interrupt
        DI
        BRA  .wait
.done:  RET

ticks:     .word 0
s_title:   .asciz "timer interrupts\n"
s_sum:     .asciz "sum of squares 1..1000 = "
s_during:  .asciz "interrupted during the sum: "
s_yes:     .asciz "yes\n"
s_no:      .asciz "no\n"
s_sleep:   .asciz "sleep "
s_colon:   .asciz ": "
s_ticks:   .asciz " ticks\n"
s_stopped: .asciz "timer off, tick count unchanged: "
s_syscall: .asciz "swi: hello from a system call\n"
s_done:    .asciz "done\n"
s_fatal:   .asciz "TRAP\n"

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/mul.s"
