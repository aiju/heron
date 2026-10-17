; interrupts: studies/v2_isa/programs/interrupts.s with RFC 0029's vectors
; and RFC 0040's timer. The vectors are at vbr + offset, vbr 0x8000_0000
; from reset, which the supervisor's window maps onto physical 0 up, this
; table; SWI #n has a vector of its own at vbr + 0x100 + 4n. The handlers
; run in the window, and reach the program's data through context 0's map.
;
; The CPU card's timer ticks at level 6 (a jumper picks the counter bit:
; here bit 10, every 2048 bus clocks); the tick counts ticks while the main
; program does interruptible work, then sleeps with HALT for exact numbers
; of ticks; and two system calls through SWI.
;
;! tick-bit: 10

        .org 0x00
        JMP  start              ; reset
        .org 0x04
        JMP  fatal              ; non-maskable interrupt
        .org 0x08
        JMP  fatal              ; illegal instruction
        .org 0x10
        JMP  fatal              ; divide error
        .org 0x14
        JMP  fatal              ; address error
        .org 0x18
        JMP  fatal              ; tag check
        .org 0x1C
        JMP  fatal              ; privilege violation
        .org 0x20
        JMP  fatal              ; page fault
        .org 0x24
        JMP  fatal              ; trace
        .org 0x54
        JMP  isr                ; level 6: the timer's tick
        .org 0x100
        JMP  sys_putc           ; SWI #0
        .org 0x104
        JMP  sys_puts           ; SWI #1
        .org 0x108

TICKCLR = 0xF0004004            ; the CPU card's timer: clear the tick

SYS_PUTC = 0                    ; system call numbers (SWI #n), see systab
SYS_PUTS = 1

start:  MOV  sp, #0x100000      ; top of RAM
        CALL main
        HALT                    ; main returns with interrupts off: stops

; ---- interrupt and trap handlers ----

; isr: count a tick. It must clear the tick, or level 6 would be taken
; again straight after RTI.
isr:    INC  [ticks]
        PUSH r1
        MOV  r1, #1
        MOV  [TICKCLR], r1
        POP  r1
        RTI

; the system calls, one vector each: the caller's r1-r4 are the
; arguments, and every register is preserved
sys_putc:
        SAVE r1-r7
        BSR  putc
        RESTORE r1-r7
        RTI
sys_puts:
        SAVE r1-r7
        BSR  puts
        RESTORE r1-r7
        RTI

; fatal: any other trap. Interrupts are off in a trap, so HALT really stops.
fatal:  LEA  r1, [s_fatal]
        BSR  puts
        HALT

; ---- main ----

main:   SAVE r7-r10
        LEA  r1, [s_title]
        BSR  puts

        CLR  [ticks]
        MOV  r1, #1
        MOV  [TICKCLR], r1
        EI

        ; Work with interrupts firing: the sum of i*i for i = 1000 down to 1.
        ; The ISR runs between any two instructions here, so it must preserve
        ; r1 (live from MOV to ADD).
        MOV  r8, #0             ; r8 = sum
        MOV  r9, #1000          ; r9 = i
.sq:    MOV  r1, r9
        MULU r0:r1, r9
        ADD  r8, r1
        DBNZ r9, .sq
        MOV  r10, [ticks]       ; ticks during the work (not printed: timing)
        LEA  r1, [s_sum]
        BSR  puts
        MOV  r1, r8
        BSR  print_u32
        BSR  newline
        LEA  r1, [s_during]
        BSR  puts
        LEA  r1, [s_yes]
        TST  r10, r10
        BNE  .some
        LEA  r1, [s_no]
.some:  BSR  puts

        ; sleep for exact numbers of ticks
        MOV  r1, #10
        BSR  timed_sleep
        MOV  r1, #25
        BSR  timed_sleep

        ; hold the timer off: no more ticks
        DI
        SPL  #6
        EI
        MOV  r8, [ticks]
        MOV  r9, #5000          ; idle a while with interrupts enabled
.idle:  DBNZ r9, .idle
        DI
        SPL  #0
        LEA  r1, [s_stopped]
        BSR  puts
        LEA  r1, [s_yes]
        CMP  r8, [ticks]
        BEQ  .same
        LEA  r1, [s_no]
.same:  BSR  puts

        LEA  r1, [s_syscall]    ; system calls
        SWI  #SYS_PUTS
        MOV  r1, #10
        SWI  #SYS_PUTC
        LEA  r1, [s_done]
        BSR  puts
        RESTORE r7-r10
        RET

; timed_sleep: r1 = ticks. Sleep, then print "sleep N: M ticks" where M is
; measured around the sleep (with interrupts off at both ends, so it's exact).
timed_sleep:
        SAVE r7-r9
        MOV  r8, r1
        DI
        MOV  r9, [ticks]
        BSR  sleep
        NEG  r9
        ADD  r9, [ticks]        ; r9 = ticks slept
        EI
        LEA  r1, [s_sleep]
        BSR  puts
        MOV  r1, r8
        BSR  print_u32
        LEA  r1, [s_colon]
        BSR  puts
        MOV  r1, r9
        BSR  print_u32
        LEA  r1, [s_ticks]
        BSR  puts
        RESTORE r7-r9
        RET

; sleep: wait until r1 more ticks have been counted. Call with interrupts
; disabled; returns with them disabled. The test and the HALT must not be
; separated by a tick, or HALT would sleep through it: so the test runs with
; interrupts off, and EI; HALT is used because an interrupt can't be taken
; right after EI, only once HALT is waiting.
sleep:  ADD  r1, [ticks]        ; r1 = the tick count to wait for
.wait:  CMP  r1, [ticks]
        BLS  .done              ; reached it
        EI
        HALT                    ; wait for the next interrupt
        DI
        BRA  .wait
.done:  RET

        .align 4
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
s_syscall: .asciz "swi: hello from a system call"
s_done:    .asciz "done\n"
s_fatal:   .asciz "TRAP\n"
        .align 2

        .include "../../v2_isa/programs/lib/console.s"
        .include "../../v2_isa/programs/lib/print.s"
