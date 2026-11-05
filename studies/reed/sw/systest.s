; systest: RFC 0029's system half on Reed, against draft 2's system
; simulator. Each test prints what it found; every exception is logged
; (vector, saved PC, sr, far, fsr) at LOG, which the harness compares with
; the reference's as well as the output.
;
; Both machines start at physical 0: the reference with PC 0x8000_0000 (the
; window), Reed with PC 0 and the page map off, where an address is
; physical (bit 31 aside). The supervisor's code is assembled in the window
; and the first jump goes there; everything the supervisor touches is
; there too. The page map (context 0) is set up for the user's tests and
; turned on with ctx's bit 31, Reed's enable, which the reference ignores.
; The user's code is at UCODE, mapped onto itself.

CONSOLE = 0xFFFFFF00
W       = 0x80000000            ; the window
LOG     = W + 0x10000           ; the exception log
SSTACK  = W + 0x20000           ; the supervisor's stack
SR_FAR  = 9
SR_FSR  = 10
SR_CTX  = 11
SR_MAPA = 12
SR_MAPD = 13
SR_BANK = 14

UCODE   = 0x5000                ; user code: V, X
UDATA   = 0x9000                ; user data, two pages: V, W
NOPAGE  = 0xA000                ; not mapped
ROPAGE  = 0xB000                ; V
NXPAGE  = 0xC000                ; V, W, not X
USTACK  = UDATA + 0xF00

        .org W + 0x00
        JMP  boot               ; reset
        .org W + 0x08
        JMP  h_illegal
        .org W + 0x10
        JMP  h_divide
        .org W + 0x14
        JMP  h_address
        .org W + 0x1C
        JMP  h_priv
        .org W + 0x20
        JMP  h_page
        .org W + 0x100
        JMP  h_swi0             ; SWI #0: logged
        .org W + 0x104
        JMP  h_exit             ; SWI #1: back to the supervisor's test
        .org W + 0x10C
        JMP  h_swi3
        .org W + 0x110
        JMP  h_swi4

        .org W + 0x200
boot:   MOV  r1, #start             ; (absolute: Reed comes here at 0x200)
        JMP  r1

; ---- the handlers ----

; r1 = the vector (pushed: the frame is sp + 16, PC, and sp + 12, sr, below
; r2, r3 and r1). Logs vector, saved PC, saved sr, far, fsr. Then the saved
; PC is [redirect] if that is set (once), else a fault's moves on by [skip]
trapped:
        SAVE r2-r3
        MOV  r2, [logp]
        MOV  [r2], r1
        MOV  r3, [sp + 16]
        MOV  [r2 + 4], r3
        MOV  r3, [sp + 12]
        MOV  [r2 + 8], r3
        MFSR r3, SR_FAR
        MOV  [r2 + 12], r3
        MFSR r3, SR_FSR
        MOV  [r2 + 16], r3
        ADD  r2, #20
        MOV  [logp], r2
        MOV  r3, [redirect]
        CMP  r3, #0
        BEQ  .skip
        MOV  [sp + 16], r3
        MOV  r3, #0
        MOV  [redirect], r3
        BRA  .out
.skip:  CMP  r1, #0x100
        BCS  .out               ; a SWI: the saved PC is the next one already
        MOV  r3, [sp + 16]
        ADD  r3, [skip]
        MOV  [sp + 16], r3
.out:   RESTORE r2-r3
        POP  r1
        RTI

h_illegal:
        PUSH r1
        MOV  r1, #0x08
        BRA  trapped
h_divide:
        PUSH r1
        MOV  r1, #0x10
        BRA  trapped
h_address:
        PUSH r1
        MOV  r1, #0x14
        BRA  trapped
h_priv:
        PUSH r1
        MOV  r1, #0x1C
        BRA  trapped
h_swi0:
        PUSH r1
        MOV  r1, #0x100
        BRA  trapped
h_swi3:
        PUSH r1
        MOV  r1, #0x10C
        BRA  trapped
h_swi4:
        PUSH r1
        MOV  r1, #0x110
        BRA  trapped
; a page fault: when [fix] is set, map the faulting page (context 0) as
; [fixentry] says, onto the same physical page, and retry
h_page:
        PUSH r1
        MOV  r1, [fix]
        CMP  r1, #0
        BEQ  .rec
        SAVE r2-r3
        MFSR r2, SR_FAR
        LSR  r2, #12
        MTSR SR_MAPA, r2
        LSL  r2, #12
        OR   r2, [fixentry]
        MTSR SR_MAPD, r2
        RESTORE r2-r3
        MOV  r1, #0
        MOV  [fix], r1
.rec:   MOV  r1, #0x20
        BRA  trapped
; SWI #1 from user mode: logged, then back to the supervisor at [exit_pc]
; with sr S
h_exit:
        PUSH r1
        MOV  r1, #0x104
        SAVE r2-r3
        MOV  r2, [logp]
        MOV  [r2], r1
        MOV  r3, [sp + 16]
        MOV  [r2 + 4], r3
        MOV  r3, [sp + 12]
        MOV  [r2 + 8], r3
        ADD  r2, #20
        MOV  [logp], r2
        MOV  r3, [exit_pc]
        MOV  [sp + 16], r3
        MOV  r3, #0x80000000
        MOV  [sp + 12], r3
        RESTORE r2-r3
        POP  r1
        RTI

; ---- printing ----

; print the string at r1 (r1, r2 changed)
puts:   MOVS r2, byte [r1]
        BEQ  .done
        MOV  byte [CONSOLE], r2
        ADD  r1, #1
        BRA  puts
.done:  RET

; print r1 in hex, then a space (r1-r3 changed)
puthex: MOV  r3, #8
.l:     MOV  r2, r1
        LSR  r2, #28
        CMP  r2, #10
        BLT  .d
        ADD  r2, #39
.d:     ADD  r2, #48
        MOV  byte [CONSOLE], r2
        LSL  r1, #4
        SUB  r3, #1
        BNE  .l
        MOV  r2, #32
        MOV  byte [CONSOLE], r2
        RET

newline:
        MOV  r2, #10
        MOV  byte [CONSOLE], r2
        RET

; enter user mode at r3 (bank 1), coming back at r4 (SWI #1)
user:   MOV  [exit_pc], r4
        PUSH r3
        MOV  r3, #0x0000000C    ; user mode, N and Z
        PUSH r3
        RTI

; ---- the tests ----

start:  MOV  sp, #SSTACK
        MOV  r1, #LOG
        MOV  [logp], r1
        MOV  r1, #0
        MOV  [skip], r1
        MOV  [redirect], r1

        ; the status register after reset, ccr, and sr's IPL and flags
        MOV  r1, #s_sr
        BSR  puts
        MFSR r1, sr
        BSR  puthex
        MOV  r5, #0x0F
        MTSR ccr, r5
        MFSR r1, ccr
        BSR  puthex
        MOV  r5, #0x05000009
        MTSR sr, r5
        MFSR r1, sr
        BSR  puthex
        MOV  r5, #0
        MTSR sr, r5
        SPL  #3
        MFSR r1, sr
        BSR  puthex
        SPL  #0
        EI
        MFSR r1, sr
        BSR  puthex
        DI
        MFSR r1, sr
        BSR  puthex
        BSR  newline

        ; SWIs: the next instruction's PC; the flags stay
        MOV  r1, #s_swi
        BSR  puts
        MOV  r5, #0x5
        MTSR ccr, r5
        SWI  #3
        SWI  #4
        MFSR r1, ccr
        BSR  puthex
        BSR  newline

        ; an illegal instruction (cell 0x00), skipped
        MOV  r1, #s_ill
        BSR  puts
        MOV  r1, #2
        MOV  [skip], r1
        MOV  r6, #0x1234
        .half 0x0000
        MOV  r1, r6
        BSR  puthex
        BSR  newline

        ; divide by zero: the registers and flags stay
        MOV  r1, #s_div
        BSR  puts
        MOV  r5, #0xA
        MTSR ccr, r5
        MOV  r0, #77
        MOV  r6, #1000
        MOV  r7, #0
        DIVU r0:r6, r7
        MFSR r1, ccr
        BSR  puthex
        MOV  r1, r6
        BSR  puthex
        MOV  r1, r0
        BSR  puthex
        BSR  newline

        ; misaligned accesses: far, and the registers they address memory
        ; with unchanged
        MOV  r1, #s_mis
        BSR  puts
        MOV  r6, #W + 0x30001
        MOV  r7, [r6]
        MOV  r7, [r6]+
        MOV  r1, r6
        BSR  puthex
        MOV  r6, #W + 0x30002
        MOV  [r6], r7
        MOV  r7, -[r6]
        MOV  r1, r6
        BSR  puthex
        MOV  r6, #W + 0x30003
        MOV  r7, half [r6]
        MFSR r1, SR_FAR
        BSR  puthex
        BSR  newline

        ; the page map, context 0: user code and data, a read-only page and
        ; a page without X, each onto the same physical page
        MOV  r1, #s_map
        BSR  puts
        MOV  r2, #UCODE >> 12
        MTSR SR_MAPA, r2
        MOV  r3, #UCODE | 5
        MTSR SR_MAPD, r3
        MOV  r2, #UDATA >> 12
        MTSR SR_MAPA, r2
        MOV  r3, #UDATA | 3
        MTSR SR_MAPD, r3
        MOV  r3, #UDATA + 0x1000 | 3
        MTSR SR_MAPD, r3        ; (mapa moved on: the next page)
        MOV  r2, #ROPAGE >> 12
        MTSR SR_MAPA, r2
        MOV  r3, #ROPAGE | 1
        MTSR SR_MAPD, r3
        MOV  r3, #NXPAGE | 3
        MTSR SR_MAPD, r3
        MOV  r3, #0x80000000    ; context 0, and Reed's map on
        MTSR SR_CTX, r3
        MFSR r1, SR_MAPA
        BSR  puthex
        ; the supervisor reaches the translated space too
        MOV  r3, #0x5A5A
        MOV  [UDATA + 0x10], r3
        MOV  r1, [W + UDATA + 0x10]
        BSR  puthex
        BSR  newline

        ; user mode: bank 1, its registers from MTUR; RTI into it
        MOV  r1, #s_user
        BSR  puts
        MOV  r2, #1
        MTSR SR_BANK, r2
        MOV  r3, #USTACK
        MTUR sp, r3
        MOV  r3, #0x11
        MTUR r1, r3
        MOV  r3, #W + 0x40
        MTUR r4, r3
        MOV  r3, #ROPAGE
        MTUR r5, r3
        MOV  r3, #NOPAGE
        MTUR r6, r3
        MOV  r3, #UDATA + 0x1004
        MTUR r7, r3
        MOV  r1, #2
        MOV  [skip], r1
        MOV  r3, #user1
        MOV  r4, #back1
        BRA  user
back1:  MFSR r1, sr
        BSR  puthex
        MFUR r1, r1
        BSR  puthex
        MFUR r1, r2
        BSR  puthex
        MFUR r1, r3
        BSR  puthex
        MOV  r1, [W + UDATA + 0x1004]
        BSR  puthex
        MFSR r1, SR_FSR
        BSR  puthex
        BSR  newline

        ; a fetch from a page without X: the saved PC is the target's
        MOV  r1, #s_nx
        BSR  puts
        MOV  r1, #user2b
        MOV  [redirect], r1
        MOV  r3, #user2
        MOV  r4, #back2
        BRA  user
back2:  MFSR r1, SR_FAR
        BSR  puthex
        MFSR r1, SR_FSR
        BSR  puthex
        BSR  newline

        ; a page fault fixed: the user's write to an unmapped page, mapped
        ; by the handler, retried
        MOV  r1, #s_fix
        BSR  puts
        MOV  r1, #1
        MOV  [fix], r1
        MOV  r1, #NOPAGE | 3
        MOV  [fixentry], r1
        MOV  r3, #user3
        MOV  r4, #back3
        BRA  user
back3:  MOV  r1, [W + NOPAGE + 4]
        BSR  puthex
        BSR  newline

        MOV  r1, #s_end
        BSR  puts
        MOV  r1, [logp]
        SUB  r1, #LOG
        BSR  puthex
        BSR  newline
        DI
        HALT

s_sr:   .ascii "sr: \0"
s_swi:  .ascii "swi: \0"
s_ill:  .ascii "illegal: \0"
s_div:  .ascii "divide: \0"
s_mis:  .ascii "misaligned: \0"
s_map:  .ascii "map: \0"
s_user: .ascii "user: \0"
s_nx:   .ascii "no execute: \0"
s_fix:  .ascii "fix: \0"
s_end:  .ascii "log: \0"
        .align 4
logp:   .word 0
skip:   .word 0
redirect: .word 0
exit_pc: .word 0
fix:    .word 0
fixentry: .word 0

; ---- user code, at UCODE (virtual = physical) ----

        .org UCODE
user1:  ADD  r1, #1             ; 0x12
        MOV  r2, [UDATA + 0x10] ; the supervisor's 0x5A5A
        SWI  #0
        EI                      ; privileged: a violation, skipped
        MOV  r3, [r4]           ; the window from user mode: a page fault
        MOV  r3, [r5]           ; read only: reading is fine
        MOV  [r5], r3           ; but not writing
        MOV  r3, [r6]           ; not mapped
        MOV  r3, #0x77
        MOV  [r7], r3           ; the second data page
        SWI  #1
user2:  JMP  NXPAGE             ; a fetch from a page without X
user2b: SWI  #1
user3:  MOV  r3, #0x99
        MOV  [r6 + 4], r3       ; mapped by the handler, retried
        SWI  #1
