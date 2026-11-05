; Reed's nucleus: a small preemptive kernel on Reed's system half (RFC
; 0029 as Reed has it), to run on the model and, cut short, at chip level.
;
; Processes run in user mode, each in a register bank and a page map
; context of its own (pid + 1 for both), so a switch saves nothing: it
; rewrites the trap frame, sets bank and ctx, and returns. The timer
; (the IO board's 82C54, counter 0 in mode 0, interrupt level 6)
; preempts; SWIs are the system calls; page faults in a process's data
; and stack areas map a zeroed page from the pool (demand-zero), any
; other fault kills the process. When none is left, the kernel prints
; what each did and halts.
;
; The console is UART 0, or, with [outmode] 0 (for the chip-level run,
; whose UART takes its baud rate's time), a buffer in RAM at OUTBUF. What
; each process did (its entry's state, how it ended, its exit code or
; why it was killed, its page faults) doesn't depend on the timer's
; timing, and is what the chip-level run is checked by.
;
; The kernel runs in the window (0x8000_0000 up, physical 0 up) with
; interrupts off; each process's code is in a page of its own at the
; same virtual address as physical (UCODE + 0x1000 x pid).

W       = 0x80000000
UART    = 0xC0000000            ; UART 0: THR (byte) at +0, LSR at +10
TIMER   = 0xC0002000            ; the 82C54: counter 0 at +0, its control at +6
IC      = 0xC0005800            ; the interrupt controller: vector; IPL as sr has it
KSTACK  = W + 0x20000
POOL    = 0x100000              ; physical pages for demand-zero, from here
SR_FAR  = 9
SR_FSR  = 10
SR_CTX  = 11
SR_MAPA = 12
SR_MAPD = 13
SR_BANK = 14

NPROC   = 4
UCODE   = 0x40000               ; process k's code at UCODE + 0x1000 k
DATA_LO = 0x100000              ; each process's demand-zero data
DATA_HI = 0x200000
STACK_LO = 0x3F0000             ; and stack
STACK_HI = 0x400000
SLICE   = 600                   ; the timer's count: about 330 us

OUTBUF  = W + 0x30000

; a process's entry: state (0 none, 1 ready, 2 done), PC, sr, ticks,
; page faults, how it ended (1 exit, 2 killed), its exit code or why
P_STATE = 0
P_PC    = 4
P_SR    = 8
P_TICKS = 12
P_FAULTS = 16
P_HOW   = 20
P_CODE  = 24
P_SIZE  = 28

        .org W + 0x00
        JMP  boot
        .org W + 0x08
        JMP  bad_illegal
        .org W + 0x10
        JMP  bad_divide
        .org W + 0x14
        JMP  bad_address
        .org W + 0x1C
        JMP  bad_privilege
        .org W + 0x20
        JMP  page_fault
        .org W + 0x3C
        RTI                     ; (no level up any more: spurious)
        .org W + 0x54
        JMP  tick               ; level 6, the timer
        .org W + 0x58
        JMP  frame              ; level 7, the video's frame (at chip level: the model has no video)
        .org W + 0x100
        JMP  sys_putc           ; SWI #0: r1 a byte to the console
        .org W + 0x104
        JMP  sys_yield          ; SWI #1
        .org W + 0x108
        JMP  sys_exit           ; SWI #2
        .org W + 0x10C
        JMP  sys_getpid         ; SWI #3: r1 = pid

        .org W + 0x200
; the video's frame: a write to its control register acknowledges it
frame:  PUSH r1
        MOV  r1, #0
        MOV  half [0xF0000400], r1
        POP  r1
        RTI

boot:   MOV  r1, #kmain         ; (absolute: Reed comes here at 0x200)
        JMP  r1

; ---- the console ----
;
; (A call leaves its return address in r7: a routine that calls another
; keeps r7 on the stack.)

; r1: a byte (r2 changed)
putc:   MOV  r2, [outmode]
        CMP  r2, #0
        BEQ  .ram
.w:     MOV  r2, byte [UART + 10]
        AND  r2, #0x20
        BEQ  .w
        MOV  byte [UART], r1
        RET
.ram:   MOV  r2, [outp]
        MOV  byte [r2], r1
        ADD  r2, #1
        MOV  [outp], r2
        RET

; the string at r1 (r1-r3 changed)
puts:   PUSH r7
        MOV  r3, r1
.l:     MOVS r1, byte [r3]
        BEQ  .done
        BSR  putc
        ADD  r3, #1
        BRA  .l
.done:  POP  r7
        RET

; r1 in decimal (r1-r5 changed)
putdec: MOV  r4, #numbuf + 11
        MOV  r5, #0
        MOV  byte [r4], r5
.l:     SUB  r4, #1
        MOV  r0, #0
        MOV  r5, #10
        DIVU r0:r1, r5          ; r1 = r1 / 10, r0 = the digit
        ADD  r0, #48
        MOV  byte [r4], r0
        CMP  r1, #0
        BNE  .l
        MOV  r1, r4
        BRA  puts

; r1 in hex (r1-r5 changed)
puthex: PUSH r7
        MOV  r4, r1
        MOV  r5, #8
.l:     MOV  r1, r4
        LSR  r1, #28
        CMP  r1, #10
        BLT  .d
        ADD  r1, #39
.d:     ADD  r1, #48
        BSR  putc
        LSL  r4, #4
        SUB  r5, #1
        BNE  .l
        POP  r7
        RET

; ---- the timer ----

; counter 0 in mode 0: it counts SLICE down and raises OUT0 (TINT) at the
; end, until the count is written again
timer:  MOV  r1, #0x30          ; counter 0, LSB then MSB, mode 0
        MOV  byte [TIMER + 6], r1
        MOV  r1, #SLICE & 0xFF
        MOV  byte [TIMER], r1
        MOV  r1, #SLICE >> 8
        MOV  byte [TIMER], r1
        RET

; ---- processes ----

; r6 = the current process's entry
current:
        MOV  r6, [cur]
        MOV  r0, #P_SIZE
        MULU r0:r6, r0
        ADD  r6, #procs
        RET

; save the frame (sp: sr, PC) into the current process's entry
save:   PUSH r7
        BSR  current
        MOV  r1, [sp + 4]       ; (sp + 4: r7 on top)
        MOV  [r6 + P_SR], r1
        MOV  r1, [sp + 8]
        MOV  [r6 + P_PC], r1
        POP  r7
        RET

; switch to the next ready process after the current one, round robin,
; through the frame: never returns. None ready: the end.
schedule:
        MOV  r8, #NPROC
.l:     MOV  r1, [cur]
        ADD  r1, #1
        CMP  r1, #NPROC
        BLT  .ok
        MOV  r1, #0
.ok:    MOV  [cur], r1
        BSR  current
        MOV  r1, [r6 + P_STATE]
        CMP  r1, #1
        BEQ  .go
        SUB  r8, #1
        BNE  .l
        BRA  the_end
.go:    MOV  r1, [r6 + P_SR]
        MOV  [sp], r1
        MOV  r1, [r6 + P_PC]
        MOV  [sp + 4], r1
        MOV  r1, [cur]
        ADD  r1, #1
        MTSR SR_BANK, r1
        OR   r1, #0x80000000    ; (Reed's page map on)
        MTSR SR_CTX, r1
        RTI

; map physical page r3 (an address) at virtual r2 in context r1, with
; flags r4 (r2 changed)
map:    LSR  r2, #12
        LSL  r1, #10            ; mapa = context x 1024 + page (Reed's 4 MB contexts)
        ADD  r2, r1
        MTSR SR_MAPA, r2
        OR   r3, r4
        MTSR SR_MAPD, r3
        RET

; ---- the start ----

kmain:  MOV  sp, #KSTACK
        MOV  r1, #s_hello
        BSR  puts
        ; the page map's contents are undefined after reset: the
        ; processes' contexts (1 to NPROC) cleared, every entry invalid
        MOV  r1, #1024
        MTSR SR_MAPA, r1
        MOV  r2, #0
        MOV  r3, #1024 * NPROC
.c:     MTSR SR_MAPD, r2        ; (mapa moves on)
        SUB  r3, #1
        BNE  .c
        ; each process: its code page, mapped onto itself (V, X), ready
        MOV  r9, #0
.p:     MOV  [cur], r9
        BSR  current
        MOV  r1, #1
        MOV  [r6 + P_STATE], r1
        MOV  r1, r9
        MOV  r2, #0x1000
        MULU r0:r1, r2
        ADD  r1, #UCODE
        MOV  [r6 + P_PC], r1
        MOV  r2, #0x40000000    ; user mode, interrupts on
        MOV  [r6 + P_SR], r2
        MOV  r3, r1
        MOV  r2, r1
        MOV  r1, r9
        ADD  r1, #1
        MOV  r4, #5
        BSR  map
        ; its sp, in the stack area
        MOV  r1, r9
        ADD  r1, #1
        MTSR SR_BANK, r1
        MOV  r1, #STACK_HI
        MTUR sp, r1
        ADD  r9, #1
        CMP  r9, #NPROC
        BLT  .p
        ; the timer, its level let in (IPL 0), and the first process
        BSR  timer
        SPL  #0
        MOV  r1, #NPROC - 1
        MOV  [cur], r1          ; (schedule takes the one after: 0)
        MOV  r1, #0
        PUSH r1                 ; a frame to rewrite
        PUSH r1
        BRA  schedule

; ---- interrupts and system calls ----

tick:   BSR  timer              ; the count again: TINT goes
        BSR  save
        MOV  r1, [r6 + P_TICKS]
        ADD  r1, #1
        MOV  [r6 + P_TICKS], r1
        MOV  r1, [nticks]
        ADD  r1, #1
        MOV  [nticks], r1
        BRA  schedule

sys_putc:
        MFUR r1, r1
        BSR  putc
        RTI

sys_yield:
        BSR  save
        BRA  schedule

sys_exit:
        BSR  current
        MOV  r1, #2
        MOV  [r6 + P_STATE], r1
        MOV  r1, #1
        MOV  [r6 + P_HOW], r1
        MFUR r1, r1             ; the exit code
        MOV  [r6 + P_CODE], r1
        BRA  schedule

sys_getpid:
        MOV  r1, [cur]
        MTUR r1, r1
        RTI

; ---- faults ----

; a page fault: in the data or stack area, not mapped (fsr bit 0) and not
; the window's: a zeroed page from the pool, mapped V, W; else the end of
; the process
page_fault:
        MFSR r10, SR_FAR
        MFSR r11, SR_FSR
        MOV  r1, r11
        AND  r1, #1
        BEQ  kill
        MOV  r1, r10
        CMP  r1, #DATA_LO
        BCC  .stack
        CMP  r1, #DATA_HI
        BCC  .ok
.stack: CMP  r1, #STACK_LO
        BCC  kill
        CMP  r1, #STACK_HI
        BCS  kill
.ok:    MOV  r3, [pool]         ; the page: zeroed through the window
        MOV  r1, r3
        ADD  r1, #0x1000
        MOV  [pool], r1
        MOV  r1, r3
        OR   r1, #W
        MOV  r2, #1024
        MOV  r5, #0
.z:     MOV  [r1]+, r5
        SUB  r2, #1
        BNE  .z
        BSR  current
        MOV  r1, [r6 + P_FAULTS]
        ADD  r1, #1
        MOV  [r6 + P_FAULTS], r1
        MOV  r1, [cur]
        ADD  r1, #1
        MOV  r2, r10
        MOV  r4, #3
        BSR  map
        RTI                     ; (the instruction again)

; (r11, why: fsr for a page fault, 0x100 + the vector for the others)
bad_illegal:
        MOV  r11, #0x108
        BRA  kill
bad_divide:
        MOV  r11, #0x110
        BRA  kill
bad_address:
        MFSR r10, SR_FAR
        MOV  r11, #0x114
        BRA  kill
bad_privilege:
        MOV  r11, #0x11C
kill:   MOV  r1, #s_kill
        BSR  puts
        MOV  r1, [cur]
        BSR  putdec
        MOV  r1, #s_at
        BSR  puts
        MOV  r1, [sp + 4]
        BSR  puthex
        MOV  r1, #s_why
        BSR  puts
        MOV  r1, r11
        BSR  puthex
        MOV  r1, #s_nl
        BSR  puts
        BSR  current
        MOV  r1, #2
        MOV  [r6 + P_STATE], r1
        MOV  [r6 + P_HOW], r1
        MOV  [r6 + P_CODE], r11
        BRA  schedule

; ---- the end: what each did ----

the_end:
        MOV  r1, #s_end
        BSR  puts
        MOV  r9, #0
.p:     MOV  [cur], r9
        MOV  r1, #s_proc
        BSR  puts
        MOV  r1, r9
        BSR  putdec
        BSR  current
        MOV  r1, #s_faults
        BSR  puts
        MOV  r1, [r6 + P_FAULTS]
        BSR  putdec
        MOV  r1, #s_ticks
        BSR  puts
        MOV  r1, [r6 + P_TICKS]
        CMP  r1, #0
        BEQ  .none
        MOV  r1, #s_some
        BRA  .say
.none:  MOV  r1, #s_zero
.say:   BSR  puts
        ADD  r9, #1
        CMP  r9, #NPROC
        BLT  .p
        MOV  r1, #s_total
        BSR  puts
        MOV  r1, [nticks]
        CMP  r1, #3
        BCS  .many
        MOV  r1, #s_few
        BRA  .t
.many:  MOV  r1, #s_many
.t:     BSR  puts
        MOV  r1, #1
        MOV  [done], r1
        DI
        HALT

s_hello: .ascii "Reed nucleus: 4 processes\n\0"
s_kill: .ascii "killed process \0"
s_at:   .ascii " at \0"
s_why:  .ascii ", why \0"
s_nl:   .ascii "\n\0"
s_end:  .ascii "all done\n\0"
s_proc: .ascii "process \0"
s_faults: .ascii ": page faults \0"
s_ticks: .ascii ", preempted \0"
s_some: .ascii "yes\n\0"
s_zero: .ascii "no\n\0"
s_total: .ascii "timer ticks: \0"
s_few:  .ascii "few\n\0"
s_many: .ascii "several\n\0"
        .align 4
outmode: .word 1
outp:   .word OUTBUF
done:   .word 0
cur:    .word 0
nticks: .word 0
pool:   .word POOL
numbuf: .space 12
procs:  .space P_SIZE * NPROC

; ---- the processes (user mode): each at UCODE + 0x1000 x pid ----

; 0: counts to 400000 in a loop the timer cuts into, printing a mark
; every 100000; then its sum
        .org UCODE
p0:     MOV  r5, #0
        MOV  r6, #0
.l:     ADD  r6, r5
        ADD  r5, #1
        MOV  r1, r5
        AND  r1, #0x3FFF
        BNE  .n
        MOV  r1, #'a'
        SWI  #0
.n:     CMP  r5, #0x10000
        BNE  .l
        MOV  r1, #10
        SWI  #0
        MOV  r1, r6             ; the sum, 0x7FFF8000
        SWI  #2

; 1: prints its pid and letters, yielding after each
        .org UCODE + 0x1000
p1:     SWI  #3                 ; r1 = pid
        ADD  r1, #48
        SWI  #0
        MOV  r5, #8
.l:     MOV  r1, #'b'
        SWI  #0
        SWI  #1
        SUB  r5, #1
        BNE  .l
        MOV  r1, #10
        SWI  #0
        MOV  r1, #8
        SWI  #2

; 2: fills 64 KB of its data area (sixteen demand-zero pages) and its
; stack, then sums the data: 'c' and the sum's low byte as a letter
        .org UCODE + 0x2000
p2:     MOV  r4, #DATA_LO
        MOV  r5, #0
.f:     MOV  [r4]+, r5
        ADD  r5, #1
        CMP  r5, #0x4000
        BNE  .f
        MOV  r1, #1234
        PUSH r1
        PUSH r1
        POP  r2
        POP  r3
        ADD  r2, r3             ; 2468
        MOV  r4, #DATA_LO
        MOV  r5, #0
        MOV  r6, #0
.s:     ADD  r6, [r4]+
        ADD  r5, #1
        CMP  r5, #0x4000
        BNE  .s
        CMP  r6, #0x7FFE000     ; 0 + 1 + ... + 0x3FFF
        BNE  .bad
        CMP  r2, #2468
        BNE  .bad
        MOV  r1, #'c'
        SWI  #0
        MOV  r1, #10
        SWI  #0
        MOV  r1, r6
        SWI  #2
.bad:   MOV  r1, #'X'
        SWI  #0
        MOV  r1, #0
        SWI  #2

; 3: tries the kernel's memory through the window: killed
        .org UCODE + 0x3000
p3:     MOV  r1, #'d'
        SWI  #0
        MOV  r1, #10
        SWI  #0
        MOV  r2, #W + 0x200
        MOV  r3, [r2]
        MOV  r1, #'Y'           ; (never)
        SWI  #0
        SWI  #2
