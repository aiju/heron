; interrupts: a timer interrupt counts ticks while the main program does
; interruptible work, then sleeps with HALT for exact numbers of ticks.
; Also a software interrupt (SWI) used as a system call (draft 1b).
;
; (The system's copy: the timer is the I/O card's 82C54, counter 0 in mode
; 2 at 1 MHz, whose output sets a flag that drives IRQ2 until it is
; acknowledged; the console is lib/start.s's UART.)
;
; Nothing printed depends on how many cycles anything takes: only on the
; results of the work and on tick differences measured race-free.

; Own vector table (lib/start.s has RTI at the IRQ vector): 4 bytes per
; vector, room for a two-parcel JMP.
        .org 0x00
        JMP  start              ; reset
        .org 0x04
        JMP  isr                ; IRQ
        .org 0x08
        JMP  fatal              ; illegal instruction
        .org 0x0C
        JMP  syscall            ; SWI
        .org 0x10
        JMP  fatal              ; divide error
        .org 0x14
        JMP  fatal              ; address error
        .org 0x18

TIMER_CNT0   = 0xFFFFFFE0       ; the 82C54: counter 0
TIMER_CTRL   = 0xFFFFFFEC       ; its control word
TIMER_ACK    = 0xFFFFFEE0       ; the flag's acknowledge; all reachable as
                                ; 16-bit absolute addresses
PERIOD       = 400              ; microseconds between ticks
TIMER_ON     = 0x34             ; counter 0, LSB then MSB, mode 2 (rate generator)
TIMER_OFF    = 0x30             ; counter 0, mode 0 with no count: OUT stays low

SYS_PUTC = 0                    ; system call numbers (SWI #n), see systab
SYS_PUTS = 1

start:  MOV  sp, #0x100000      ; top of RAM
        BSR  __con_init
        CALL main
        BSR  __con_flush
        HALT                    ; main returns with interrupts off: stops

; ---- interrupt and trap handlers ----

; isr: count a tick. The CPU saves PC and the flags; the handler saves the
; register it uses and must acknowledge the timer, or the level-triggered
; IRQ would fire again straight after RTI.
isr:    PUSH r1
        MOV  r1, [ticks]
        INC  r1
        ST   r1, [ticks]
        ST   r0, byte [TIMER_ACK]   ; any write acknowledges
        POP  r1
        RTI

; syscall: SWI #n calls system call n with the caller's r1-r4 as arguments
; and preserves every register. n is in bits 11-4 of the SWI instruction,
; just before the saved PC. A number without a system call is fatal.
syscall:
        SAVE r1-r7
        MOV  r5, [sp + 32]      ; saved PC: above 7 registers and the flags
        MOV  r5, half [r5 - 2]  ; the SWI instruction
        LSR  r5, #2
        AND  r5, #0xFF << 2     ; r5 = 4n
        CMP  r5, #4 * NSYS
        BHS  fatal
        CALL [systab + r5]
        RESTORE r1-r7
        RTI

; fatal: any other trap. Interrupts are off in a trap, so HALT really stops.
fatal:  LEA  r1, [s_fatal]
        BSR  puts
        BSR  __con_flush
        HALT

        .align 4
systab: .word putc, puts
NSYS = ($ - systab) / 4

; ---- main ----

main:   SAVE r8-r10
        LEA  r1, [s_title]
        BSR  puts

        ST   r0, [ticks]
        MOV  r1, #TIMER_ON
        ST   r1, byte [TIMER_CTRL]
        MOV  r1, #PERIOD & 0xFF
        ST   r1, byte [TIMER_CNT0]
        MOV  r1, #PERIOD >> 8
        ST   r1, byte [TIMER_CNT0]
        EI

        ; Work with interrupts firing: the sum of i*i for i = 1000 down to 1.
        ; The ISR runs between any two instructions here, so it must preserve
        ; r1 (live from MOV to ADD) and the flags (from DEC to BNE).
        MOV  r8, #0             ; r8 = sum
        MOV  r9, #1000          ; r9 = i
.sq:    MOV  r1, r9
        MULU r1, r9
        ADD  r8, r1
        DEC  r9
        BNE  .sq
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

        ; stop the timer: no more ticks
        DI
        MOV  r1, #TIMER_OFF
        ST   r1, byte [TIMER_CTRL]
        ST   r0, byte [TIMER_ACK]
        EI
        MOV  r8, [ticks]
        MOV  r9, #5000          ; idle a while with interrupts enabled
.idle:  DEC  r9
        BNE  .idle
        DI
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
        RESTORE r8-r10
        RET

; timed_sleep: r1 = ticks. Sleep, then print "sleep N: M ticks" where M is
; measured around the sleep (with interrupts off at both ends, so it's exact).
timed_sleep:
        SAVE r8-r9
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
        RESTORE r8-r9
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

        .include "lib/uart.s"
        .include "lib/console.s"
        .include "lib/print.s"
