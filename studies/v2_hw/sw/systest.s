; systest: RFC 0029's system architecture and RFC 0040's interrupts on the
; draft 2 CPU. Each test prints its name and "ok", or what it got instead.
;
; The harness has mapped context 0's first megabyte one to one and starts
; here in supervisor mode, bank 0. The supervisor's stack is in the window
; (physical 0x100000, as 0x8010_0000); user mode runs in bank 1 with its
; own stack at 0xF0000; the message level's registers have their stack at
; physical 0xE0000. Exceptions vector to vbr + offset, vbr 0x8000_0000 at
; reset: physical 0 up, this table, in the window. The CPU card's registers
; are at physical 0x7000_0000 (RFC 0040, 3), 0xF000_0000 in the window.
;
;! max-cycles: 20000000
;! tick-bit: 10

SR_CCR  = 0
SR_SR   = 8
SR_FAR  = 9
SR_FSR  = 10
SR_CTX  = 11
SR_MAPA = 12
SR_MAPD = 13
SR_BANK = 14
SR_VBR  = 15

SR_S    = 0x80000000            ; sr's bits
SR_I    = 0x40000000
SR_T    = 0x20000000
SR_M    = 0x10000000
SR_IPL  = 0x0F000000

CARD    = 0xF0000000            ; the CPU card's registers, in the window
CTRL    = CARD + 0x0000
INFO    = CARD + 0x1000
REQSET  = CARD + 0x2000
REQCLR  = CARD + 0x2004
REQ     = CARD + 0x2008
CLAIM   = CARD + 0x3000
MSG     = CARD + 0x3004
RELEASE = CARD + 0x3008
MSGREAD = CARD + 0x300C
TIMER   = CARD + 0x4000
TICKCLR = CARD + 0x4004
MSGSTACK = 0x800E0000
MSGSRC  = 200                   ; the message test's source: SWI entry 200

        .org 0x00
        JMP  start              ; reset
        .org 0x04
        JMP  h_nmi              ; non-maskable interrupt
        .org 0x08
        JMP  h_illegal          ; illegal instruction
        .org 0x10
        JMP  h_divide           ; divide error
        .org 0x14
        JMP  h_address          ; address error (misaligned)
        .org 0x18
        JMP  h_tag              ; tag trap
        .org 0x1C
        JMP  h_priv             ; privilege violation
        .org 0x20
        JMP  h_page             ; page fault
        .org 0x24
        JMP  h_trace            ; trace
        .org 0x40
        JMP  h_lvl1             ; levels 1-8: vbr + 0x40 + 4(L - 1)
        JMP  h_lvl2
        JMP  h_lvl3
        JMP  h_lvl4
        JMP  h_lvl5
        JMP  h_tick             ; level 6: the card's timer
        JMP  h_lvl7
        JMP  h_lvl8
        .org 0x100
        JMP  h_exit             ; SWI #0: back to the supervisor's test
        .org 0x104
        JMP  h_swi1             ; SWI #1: report the caller's r1 and r2
        .org 0x100 + 4 * 128
        JMP  h_swi128           ; SWI #128, kept for message sources
        .org 0x100 + 4 * MSGSRC
        JMP  h_msg              ; the message test's source
        .org 0x500

USERPAGE = 0x90                 ; a page for user data, VA 0x90000
NOPAGE   = 0xA0                 ; a page left unmapped, VA 0xA0000
ROPAGE   = 0xB0                 ; read only
NXPAGE   = 0xC0                 ; no execute

; ---- exception handlers: record what happened, then resume ----

; the common part: r1 = the vector's number. Records it, the saved PC,
; FAR and FSR; skips `skip` bytes of the faulting instruction (0: retry it)
trapped:
        MOV  [t_vec], r1
        MOV  r1, [sp + 4]       ; the saved PC
        MOV  [t_pc], r1
        MFSR r1, SR_FAR
        MOV  [t_far], r1
        MFSR r1, SR_FSR
        MOV  [t_fsr], r1
        MOV  r1, [sp]           ; the saved sr
        MOV  [t_flags], r1
        INC  [t_count]
        MOV  r1, [sp + 4]
        ADD  r1, [skip]
        MOV  [sp + 4], r1
        MOV  r1, [t_save1]
        RTI

h_illegal: MOV [t_save1], r1
        MOV  r1, #0x08
        BRA  trapped
h_divide: MOV [t_save1], r1
        MOV  r1, #0x10
        BRA  trapped
h_address: MOV [t_save1], r1
        MOV  r1, #0x14
        BRA  trapped
h_tag:  MOV  [t_save1], r1
        MOV  r1, #0x18
        BRA  trapped
h_priv: MOV  [t_save1], r1
        MOV  r1, #0x1C
        BRA  trapped

; a page fault: when fixpage is set, map the faulting page (context 0)
; with fixentry's flags onto the same physical page and retry
h_page: MOV  [t_save1], r1
        MOVS r1, [fixpage]
        BEQ  .rec
        SAVE r2-r3
        MFSR r2, SR_FAR
        LSR  r2, #12            ; the page
        MTSR SR_MAPA, r2
        LSL  r2, #12
        OR   r2, [fixentry]
        MTSR SR_MAPD, r2
        RESTORE r2-r3
        CLR  [fixpage]
.rec:   MOV  r1, #0x20
        BRA  trapped

h_trace: INC [traces]
        MOV  [t_save1], r1
        MOV  r1, [sp + 4]
        MOV  [t_pc], r1
        MOV  r1, [t_save1]
        RTI

; interrupts: each level counts itself in lvl_count + 4(L - 1), keeps the
; order levels came in (lvl_seq, a nibble each), and records IPL as the
; handler sees it and the IPL it interrupted; then clears its request
h_lvl1: PUSH r1
        MOV  r1, #1
        BRA  h_level
h_lvl2: PUSH r1
        MOV  r1, #2
        BRA  h_level
h_lvl3: PUSH r1
        MOV  r1, #3
        BRA  h_level
h_lvl4: PUSH r1
        MOV  r1, #4
        BRA  h_level
h_lvl5: PUSH r1
        MOV  r1, #5
        BRA  h_level
h_lvl7: PUSH r1
        MOV  r1, #7
        BRA  h_level
h_lvl8: PUSH r1
        MOV  r1, #8
h_level:
        SAVE r2-r3
        MOV  r3, r1
        LSL  r3, #2
        LEA  r2, [lvl_count - 4]
        ADD  r2, r3
        INC  [r2]
        MOV  r2, [lvl_seq]
        LSL  r2, #4
        OR   r2, r1
        MOV  [lvl_seq], r2
        MFSR r2, SR_SR
        LSR  r2, #24
        AND  r2, #15
        MOV  [lvl_ipl], r2      ; IPL in the handler: the level
        MOV  r2, [sp + 12]      ; the sr it interrupted
        LSR  r2, #24
        AND  r2, #15
        MOV  [lvl_was], r2
        MOV  r2, #1
        LSL  r2, r1
        MOV  [REQCLR], r2       ; the request served
        MOVS r2, [nest_at]      ; nesting: at this level, raise nest_req and EI
        CMP  r2, r1
        BNE  .done
        CLR  [nest_at]
        MOV  r2, [nest_req]
        EI
        MOV  [REQSET], r2
        NOP
        NOP
        NOP
        NOP
        DI
.done:  RESTORE r2-r3
        POP  r1
        RTI

; level 6: the timer's tick
h_tick: PUSH r1
        INC  [ticks]
        MOV  r1, #1
        MOV  [TICKCLR], r1
        POP  r1
        RTI

; the non-maskable interrupt: taken whatever I and IPL
h_nmi:  PUSH r1
        INC  [nmis]
        MFSR r1, SR_SR
        MOV  [nmi_sr], r1
        POP  r1
        RTI

; the message level, vectored through SWI entry MSGSRC: in its own
; registers, the source in r1, the message in r2; it saves nothing
h_msg:  MOV  [m_src], r1
        MOV  [m_msg], r2
        MFSR r3, SR_SR
        MOV  [m_sr], r3
        MOV  [m_sp], sp
        MOV  r9, #0x666         ; the message level's r9, not the kernel's
        INC  [m_count]
        RTI

; SWI #128, from supervisor mode
h_swi128:
        INC  [swi128]
        RTI

; SWI #0: the user's test is over. Drop the frame and go back to where
; run_user was called from.
h_exit: MFSR r1, SR_SR
        MOV  [exit_flags], r1
        LEA  sp, [sp + 8]
        JMP  [continue]

; SWI #1: the caller's r1 and r2, read from its bank
h_swi1: SAVE r1-r2
        MFUR r1, r1
        MOV  [u_r1], r1
        MFUR r2, r2
        MOV  [u_r2], r2
        MOV  r1, [sp + 8]       ; the sr the SWI saved
        MOV  [swi_flags], r1
        RESTORE r1-r2
        RTI

; run_user: r1 = an entry point; runs it in user mode, bank 1, until it
; does SWI #0
run_user:
        MOV  r2, #1
        MTSR SR_BANK, r2
        MOV  r2, #0xF0000
        MTUR sp, r2
        LEA  r2, [.back]
        MOV  [continue], r2
        PUSH r1                 ; the PC
        CLR  r2
        PUSH r2                 ; the flags: user mode, interrupts off
        RTI
.back:  RET

; ---- the tests ----

start:  JMP  #0x80000000 + .win  ; run in the window, where ctx doesn't matter
.win:   MOV  sp, #0x80100000
        LEA  r1, [s_title]
        BSR  puts

        ; ---- boot state: supervisor mode, I T M IPL 0, ctx 0, bank 0
        LEA  r1, [s_boot]
        BSR  puts
        MFSR r2, SR_SR
        AND  r2, #0xFF000000
        MFSR r3, SR_CTX
        OR   r2, r3
        MFSR r3, SR_BANK
        OR   r2, r3
        MOV  r1, #SR_S
        BSR  expect
        LEA  r1, [s_vbr0]       ; vbr from reset
        BSR  puts
        MFSR r2, SR_VBR
        MOV  r1, #0x80000000
        BSR  expect

        ; ---- the special registers
        LEA  r1, [s_spr]
        BSR  puts
        MOV  r2, #0xFF
        MTSR SR_CTX, r2
        MFSR r4, SR_CTX            ; 0x7F
        CLR  r2
        MTSR SR_CTX, r2
        MOV  r2, #0x1234
        MTSR SR_BANK, r2
        MFSR r5, SR_BANK           ; 0x34
        CLR  r2
        MTSR SR_BANK, r2
        MOV  r2, #0x12345
        MTSR SR_MAPA, r2
        MFSR r6, SR_MAPA
        MOV  r2, #7
        MTSR 3, r2              ; reserved: ignored, reads 0
        MFSR r3, 3
        MTSR 9, r2              ; far and fsr: read only
        MTSR 10, r2
        MFSR r8, SR_FSR
        MFSR r9, SR_BANK
        LSL  r4, #24
        LSL  r5, #16
        OR   r4, r5
        OR   r4, r3
        OR   r4, r8
        OR   r4, r9
        MOV  r2, r4
        MOV  r1, #0x7F340000
        BSR  expect
        LEA  r1, [s_mapa]
        BSR  puts
        MOV  r2, r6
        MOV  r1, #0x12345
        BSR  expect

        ; ---- the page map: write entries through mapd, read them back
        LEA  r1, [s_mapd]
        BSR  puts
        MOV  r2, #0x1F00        ; context 1, page 0xF00
        MTSR SR_MAPA, r2
        MOV  r3, #0x12345007
        MTSR SR_MAPD, r3
        MOV  r3, #0xABCDE003
        MTSR SR_MAPD, r3           ; mapa moved on: page 0xF01
        MOV  r3, #0x55555FF5    ; bits 11-3 read as 0
        MTSR SR_MAPD, r3
        MTSR SR_MAPA, r2
        MFSR r4, SR_MAPD
        MOV  r1, #0x1F01
        MTSR SR_MAPA, r1
        MFSR r5, SR_MAPD
        MOV  r1, #0x1F02
        MTSR SR_MAPA, r1
        MFSR r6, SR_MAPD
        MFSR r7, SR_MAPA
        XOR  r4, #0x12345007
        XOR  r5, #0xABCDE003
        XOR  r6, #0x55555005
        OR   r4, r5
        OR   r4, r6
        XOR  r7, #0x1F02
        OR   r4, r7
        MOV  r2, r4
        CLR  r1
        BSR  expect

        ; set up the test pages in context 0
        MOV  r2, #USERPAGE
        MTSR SR_MAPA, r2
        MOV  r3, #USERPAGE << 12 | 7
        MTSR SR_MAPD, r3
        MOV  r2, #NOPAGE
        MTSR SR_MAPA, r2
        CLR  r3
        MTSR SR_MAPD, r3           ; invalid
        MOV  r2, #ROPAGE
        MTSR SR_MAPA, r2
        MOV  r3, #ROPAGE << 12 | 5      ; X and V, no W
        MTSR SR_MAPD, r3
        MOV  r2, #NXPAGE
        MTSR SR_MAPA, r2
        MOV  r3, #NXPAGE << 12 | 3      ; W and V, no X
        MTSR SR_MAPD, r3
        MOV  r1, #0x2468ACE0
        MOV  [USERPAGE << 12], r1       ; the user's data
        MOV  r1, #0x0FF1CE
        MOV  [0x80000000 | ROPAGE << 12], r1   ; through the window: the page has no W

        ; ---- the window: physical memory at 0x8000_0000 + pa
        LEA  r1, [s_window]
        BSR  puts
        MOV  r2, [0x80000000 | USERPAGE << 12]
        MOV  r1, #0x2468ACE0
        BSR  expect

        ; ---- user mode: bank 1, set through MTUR, read through MFUR
        LEA  r1, [s_user]
        BSR  puts
        MOV  r2, #1
        MTSR SR_BANK, r2
        MOV  r2, #0x1111
        MTUR r1, r2
        MOV  r2, #0x2222
        MTUR r2, r2
        MOV  r1, #0x5A5A
        MOV  r9, #0x9999        ; the supervisor's r9: must survive
        MOV  r1, #u_banks
        BSR  run_user
        MOV  r2, [u_r1]         ; the user's r1 + r2 at its SWI #1
        ADD  r2, [u_r2]
        CMP  r9, #0x9999
        BEQ  .r9ok
        MOV  r2, #-1
.r9ok:  MOV  r1, #0x1111 + 0x2222 + 0x10
        BSR  expect
        LEA  r1, [s_swiflags]   ; SWI from user mode saved S = 0
        BSR  puts
        MOV  r2, [swi_flags]
        AND  r2, #SR_S
        CLR  r1
        BSR  expect
        LEA  r1, [s_exitflags]  ; and the handler runs with S set, I T M clear
        BSR  puts
        MOV  r2, [exit_flags]
        AND  r2, #0xF0000000
        MOV  r1, #SR_S
        BSR  expect

        ; ---- privilege violations in user mode
        LEA  r1, [s_priv]
        BSR  puts
        CLR  [t_count]
        MOV  r1, #2
        MOV  [skip], r1
        MOV  r1, #u_priv
        BSR  run_user
        MOV  r2, [t_count]      ; EI, DI, HALT, RTI, MFSR far, MTSR ctx, MFUR, MTUR,
        MOV  r1, #12            ; SPL, MFSR sr, MTSR sr, SWI #128
        BSR  expect
        LEA  r1, [s_privvec]
        BSR  puts
        MOV  r2, [t_vec]
        MOV  r1, #0x1C
        BSR  expect

        ; ---- MTSR ccr in user mode changes only N Z C V
        LEA  r1, [s_uflags]
        BSR  puts
        MOV  r1, #u_flags
        BSR  run_user
        MOV  r2, [u_r1]         ; the user's ccr after MTSR ccr, #0xFFFFFFFF
        MOV  r1, #0x0F
        BSR  expect

        ; ---- page faults: an invalid page, retried after the handler maps it
        LEA  r1, [s_fault]
        BSR  puts
        CLR  [t_count]
        CLR  [skip]
        MOV  r1, #1
        MOV  [fixpage], r1
        MOV  r1, #7
        MOV  [fixentry], r1
        MOV  r1, #u_fault
        BSR  run_user
        MOV  r2, [t_fsr]        ; invalid entry, a user read
        MOV  r1, #0x01
        BSR  expect
        LEA  r1, [s_far]
        BSR  puts
        MOV  r2, [t_far]
        MOV  r1, #NOPAGE << 12 | 0x124
        BSR  expect
        LEA  r1, [s_retry]      ; the retried load got the value; the
        BSR  puts               ; auto-increment happened once
        MOV  r2, [u_r1]
        ADD  r2, [u_r2]
        MOV  r1, #0x99 + (NOPAGE << 12 | 0x128)
        BSR  expect

        ; unmap the page again for the next test
        MOV  r2, #NOPAGE
        MTSR SR_MAPA, r2
        CLR  r3
        MTSR SR_MAPD, r3

        ; ---- a store to a page without W
        LEA  r1, [s_wfault]
        BSR  puts
        CLR  [fixpage]
        MOV  r1, #4
        MOV  [skip], r1
        MOV  r1, #u_wfault
        BSR  run_user
        MOV  r2, [t_fsr]
        MOV  r1, #0x22          ; no W, a store
        BSR  expect
        LEA  r1, [s_wkept]      ; and memory, and the base register, unchanged
        BSR  puts
        MOV  r2, [ROPAGE << 12]
        ADD  r2, [u_r2]
        MOV  r1, #0x0FF1CE + (ROPAGE << 12)
        BSR  expect

        ; ---- a fetch from a page without X
        LEA  r1, [s_xfault]
        BSR  puts
        MOV  r1, #1
        MOV  [fixpage], r1
        MOV  r1, #7
        MOV  [fixentry], r1
        CLR  [skip]
        ; copy the user routine u_nx into the NX page, then run it there
        MOV  r1, #u_nx
        MOV  r2, #NXPAGE << 12
        MOV  r3, #(u_nx_end - u_nx + 3) / 4
.cp:    MOV  r4, [r1]+
        MOV  [r2]+, r4
        DBNZ r3, .cp
        MOV  r1, #NXPAGE << 12
        BSR  run_user
        MOV  r2, [t_fsr]
        MOV  r1, #0x44          ; no X, a fetch
        BSR  expect
        LEA  r1, [s_xpc]        ; the saved PC is the instruction's own
        BSR  puts
        MOV  r2, [t_pc]
        MOV  r1, #NXPAGE << 12
        BSR  expect

        ; ---- the user's bit 31, and the gap between 16 MB and 2 GB
        LEA  r1, [s_range]
        BSR  puts
        CLR  [fixpage]
        MOV  r1, #6
        MOV  [skip], r1
        CLR  [t_fsr]
        MOV  r1, #u_high
        BSR  run_user
        MOV  r2, [u_r1]         ; the two faults' FSRs, as the user saw them
        MOV  r1, #0x1008
        BSR  expect

        ; ---- the supervisor's own faults: bit 7, a translated address
        LEA  r1, [s_sfault]
        BSR  puts
        CLR  [fixpage]
        MOV  r1, #6
        MOV  [skip], r1
        MOV  r1, [NOPAGE << 12]
        MOV  r2, [t_fsr]
        MOV  r1, #0x81          ; invalid, in supervisor mode
        BSR  expect

        ; ---- misaligned accesses: the address error vector, FAR
        LEA  r1, [s_mis]
        BSR  puts
        MOV  r1, #2
        MOV  [skip], r1
        MOV  r3, #USERPAGE << 12 | 2
        MOV  r4, [r3]+          ; a word at an address of 2: r3 unchanged
        MOV  r2, [t_vec]
        LSL  r2, #24
        OR   r2, [t_far]
        SUB  r2, r3             ; ... + (FAR - r3) = 0x14000000 + 0
        MOV  r1, #0x14000000
        BSR  expect

        ; ---- an address nothing answers: no trap, stale data (RFC 0037, 27)
        LEA  r1, [s_buserr]
        BSR  puts
        CLR  [t_vec]
        MOV  r2, [0xA8000000]   ; region 2 (physical 0x2800_0000): no card
        MOV  r2, [t_vec]
        CLR  r1
        BSR  expect

        ; ---- divide error, illegal instruction, tag trap
        LEA  r1, [s_traps]
        BSR  puts
        MOV  r1, #2
        MOV  [skip], r1
        CLR  r2
        MOV  r3, #5
        DIVU r0:r3, r2
        MOV  r5, [t_vec]
        .align 4
        .word 0x00FF00FF        ; two ILLEGAL parcels
        MOV  r6, [t_vec]
        MOV  r3, #3
        TADD r3, r3
        MOV  r7, [t_vec]
        LSL  r5, #16
        LSL  r6, #8
        OR   r5, r6
        OR   r5, r7
        MOV  r2, r5
        MOV  r1, #0x100818
        BSR  expect

        ; ---- trace: a trap after every instruction while T is set
        LEA  r1, [s_trace]
        BSR  puts
        CLR  [traces]
        MOV  r1, #u_trace
        BSR  run_user_traced
        MOV  r2, [traces]       ; the four instructions before the SWI (one
        MOV  r1, #4             ; that traps doesn't trace: the trap clears T)
        BSR  expect

        ; ---- sr: MTSR sr keeps S; ccr is its byte 0; SPL sets IPL alone
        LEA  r1, [s_sr]
        BSR  puts
        MOV  r1, #0x05000005    ; IPL 5, Z and V; S clear in r1
        MTSR SR_SR, r1
        MFSR r2, SR_SR
        MOV  r1, #SR_S | 0x05000005
        BSR  expect
        LEA  r1, [s_spl]
        BSR  puts
        MOV  r1, #0x0A          ; N and C
        MTSR SR_CCR, r1
        SPL  #3
        MFSR r2, SR_SR
        MFSR r3, SR_CCR
        LSL  r3, #4
        OR   r2, r3
        MOV  r1, #SR_S | 0x030000AA
        BSR  expect
        SPL  #0

        ; ---- vbr: 2 KB aligned; an exception through a second table
        LEA  r1, [s_vbr]
        BSR  puts
        MOV  r1, #0x80000000 | vtab2 | 0x345
        MTSR SR_VBR, r1
        MFSR r4, SR_VBR
        CLR  [ill2]
        .align 4
        .word 0x00FF00FF        ; two ILLEGAL parcels, through vtab2
        MOV  r1, #0x80000000
        MTSR SR_VBR, r1
        MOV  r2, [ill2]
        ADD  r2, r4
        MOV  r1, #0x80000000 | vtab2 + 2
        BSR  expect
        LEA  r1, [s_vbrswi]     ; SWI goes through vbr too
        BSR  puts
        MOV  r1, #0x80000000 | vtab2
        MTSR SR_VBR, r1
        CLR  [swi128]
        SWI  #1                 ; vtab2's: counts in swi128
        MOV  r1, #0x80000000
        MTSR SR_VBR, r1
        MOV  r2, [swi128]
        MOV  r1, #1
        BSR  expect

        ; ---- the request register: set, read, clear
        LEA  r1, [s_reqreg]
        BSR  puts
        MOV  r1, #0x1FE
        MOV  [REQSET], r1
        MOV  r2, [REQ]
        MOV  [REQCLR], r1
        MOV  r3, [REQ]
        LSL  r3, #16
        OR   r2, r3
        MOV  r1, #0x1FE
        BSR  expect

        ; ---- levels: taken above IPL, the highest first
        LEA  r1, [s_levels]
        BSR  puts
        CLR  [lvl_seq]
        SPL  #3
        EI
        MOV  r1, #(1 << 2) | (1 << 3) | (1 << 5)
        MOV  [REQSET], r1       ; 5 is taken; 2 and 3 wait
        NOP
        NOP
        NOP
        NOP
        MOV  r4, [lvl_seq]
        SPL  #0                 ; then 3, then 2
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        DI
        MOV  r2, [lvl_seq]
        LSL  r4, #16
        OR   r2, r4
        MOV  r1, #0x50532
        BSR  expect
        LEA  r1, [s_lvlipl]     ; IPL in level 2's handler, and what it interrupted
        BSR  puts
        MOV  r2, [lvl_ipl]
        LSL  r2, #4
        OR   r2, [lvl_was]
        MOV  r1, #0x20
        BSR  expect

        ; ---- nesting: level 3's handler executes EI, and level 4 gets in
        LEA  r1, [s_nest]
        BSR  puts
        CLR  [lvl_seq]
        MOV  r1, #3
        MOV  [nest_at], r1
        MOV  r1, #1 << 4
        MOV  [nest_req], r1
        EI
        MOV  r1, #1 << 3
        MOV  [REQSET], r1
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        DI
        MOV  r2, [lvl_seq]
        MOV  r1, #0x34
        BSR  expect

        ; ---- level 8, and level 7 from its request bit (no message)
        LEA  r1, [s_lvl78]
        BSR  puts
        CLR  [lvl_seq]
        EI
        MOV  r1, #(1 << 7) | (1 << 8)
        MOV  [REQSET], r1
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        DI
        MOV  r2, [lvl_seq]
        MOV  r1, #0x87
        BSR  expect

        ; ---- the message register: claimed by a read, 1 while claimed
        LEA  r1, [s_claim]
        BSR  puts
        MFSR r1, SR_SR          ; the message level's registers: its sp, its r9
        OR   r1, #SR_M
        MTSR SR_SR, r1
        MOV  sp, #MSGSTACK
        MOV  r9, #0x99
        MFSR r1, SR_SR
        AND  r1, #~SR_M
        MTSR SR_SR, r1          ; the kernel's registers again
        MOV  r2, [CLAIM]
        MOV  r3, [CLAIM]
        LSL  r2, #4
        OR   r2, r3
        MOV  r1, #0x01
        BSR  expect
        LEA  r1, [s_msg]        ; the message: through SWI entry MSGSRC
        BSR  puts
        MOV  r9, #0x1234        ; the kernel's r9: must survive
        MOV  r1, #MSGSRC << 24 | 0x123456
        EI
        MOV  [MSG], r1
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        DI
        MOV  r2, [m_src]
        LSL  r2, #24
        OR   r2, [m_msg]
        MOV  r1, #MSGSRC << 24 | 0x123456
        BSR  expect
        LEA  r1, [s_msgsr]      ; in its own registers, at IPL 7
        BSR  puts
        MOV  r2, [m_sr]
        AND  r2, #SR_M | SR_IPL
        MOV  r1, #SR_M | 0x07000000
        BSR  expect
        LEA  r1, [s_msgsp]      ; its frame on its own sp
        BSR  puts
        MOV  r2, [m_sp]
        MOV  r1, #MSGSTACK - 8
        BSR  expect
        LEA  r1, [s_msgr9]      ; the kernel's registers untouched
        BSR  puts
        MOV  r2, r9
        MOV  r1, #0x1234
        BSR  expect
        LEA  r1, [s_msgfree]    ; the entry released it: a claim gets it
        BSR  puts
        MOV  r2, [CLAIM]
        MOV  [RELEASE], r2
        CLR  r1
        BSR  expect

        ; ---- the non-maskable interrupt: through the control register,
        ; whatever I and IPL; it leaves IPL alone and is taken once
        LEA  r1, [s_nmi]
        BSR  puts
        CLR  [nmis]
        SPL  #8
        MOV  r1, #9             ; NMI, and RUN kept
        MOV  [CTRL], r1
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        MOV  r2, [nmis]
        MOV  r3, [nmi_sr]
        AND  r3, #SR_I | SR_IPL
        OR   r2, r3
        MOV  r3, [CTRL]
        AND  r3, #8
        OR   r2, r3
        SPL  #0
        MOV  r1, #0x08000001
        BSR  expect

        ; ---- SWI #128 from supervisor mode
        LEA  r1, [s_swi128]
        BSR  puts
        CLR  [swi128]
        SWI  #128
        MOV  r2, [swi128]
        MOV  r1, #1
        BSR  expect

        ; ---- the board information: region 0, 2 MB, a 60 ns BCLK
        LEA  r1, [s_info]
        BSR  puts
        MOV  r2, [INFO]
        AND  r2, #0xFFFF
        MOV  r1, #0x3C10
        BSR  expect

        ; ---- the timer counts; HALT waits for its tick at level 6
        LEA  r1, [s_timer]
        BSR  puts
        MOV  r2, [TIMER]
        NOP
        NOP
        MOV  r3, [TIMER]
        CMP  r3, r2
        SETHI r2
        MOV  r1, #1
        BSR  expect
        LEA  r1, [s_halt]
        BSR  puts
        MOV  r1, #1
        MOV  [TICKCLR], r1
        CLR  [ticks]
        EI
        HALT
        DI
        MOVS r2, [ticks]
        SETNE r2
        MOV  r1, #1
        BSR  expect

        LEA  r1, [s_done]
        BSR  puts
        HALT

; run_user_traced: as run_user, with T set in the flags RTI restores
run_user_traced:
        MOV  r2, #1
        MTSR SR_BANK, r2
        MOV  r2, #0xF0000
        MTUR sp, r2
        LEA  r2, [.back]
        MOV  [continue], r2
        PUSH r1
        MOV  r2, #SR_T
        PUSH r2
        RTI
.back:  RET

; expect: r1 = the value wanted, r2 = the value got: prints "ok" or both
expect: CMP  r1, r2
        BNE  .bad
        LEA  r1, [s_ok]
        BRA  puts
.bad:   SAVE r7-r8
        MOV  r8, r2
        MOV  r7, r1
        LEA  r1, [s_want]
        BSR  puts
        MOV  r1, r7
        MOV  r2, #8
        BSR  print_hex
        LEA  r1, [s_got]
        BSR  puts
        MOV  r1, r8
        MOV  r2, #8
        BSR  print_hex
        BSR  newline
        RESTORE r7-r8
        RET

; ---- user routines: they end with SWI #0 ----

u_banks:
        ADD  r1, #0x10          ; the user's own r1 (0x1111, set through MTUR)
        SWI  #1
        SWI  #0

u_priv: EI
        DI
        HALT
        RTI
        MFSR r1, SR_FAR
        MTSR SR_CTX, r1
        MFUR r1, r2
        MTUR r1, r2
        SPL  #3
        MFSR r1, SR_SR
        MTSR SR_SR, r1
        SWI  #128
        SWI  #0

u_flags:
        MOV  r1, #-1
        MTSR SR_CCR, r1
        MFSR r1, SR_CCR
        SWI  #1
        SWI  #0

u_fault:
        MOV  r2, #NOPAGE << 12 | 0x124
        MOV  r1, [r2]+          ; faults, is retried
        ADD  r1, #0x99
        SWI  #1
        SWI  #0

u_wfault:
        MOV  r2, #ROPAGE << 12
        MOV  [r2]+, r2          ; no W: skipped, r2 unchanged
        NOP
        SWI  #1
        SWI  #0

        .align 4
u_nx:   ADD  r1, #0             ; fetching this faults, until mapped with X
        SWI  #0
u_nx_end:

u_high: MOV  r2, [0x80001000]   ; bit 31 in user mode
        MOV  r1, [t_fsr]
        AND  r1, #0x1F
        LSL  r1, #8
        MOV  r2, [0x01000000]   ; 16 MB
        MOV  r3, [t_fsr]
        AND  r3, #0x1F
        OR   r1, r3
        SWI  #1
        SWI  #0

u_trace:
        NOP
        NOP
        NOP
        NOP
        SWI  #0

; ---- data ----

        .align 4
t_vec:     .word 0
t_pc:      .word 0
t_far:     .word 0
t_fsr:     .word 0
t_flags:   .word 0
t_count:   .word 0
t_save1:   .word 0
skip:      .word 0
fixpage:   .word 0
fixentry:  .word 0
traces:    .word 0
continue:  .word 0
exit_flags: .word 0
swi_flags: .word 0
u_r1:      .word 0
u_r2:      .word 0
lvl_count: .word 0, 0, 0, 0, 0, 0, 0, 0
lvl_seq:   .word 0
lvl_ipl:   .word 0
lvl_was:   .word 0
nest_at:   .word 0
nest_req:  .word 0
ticks:     .word 0
nmis:      .word 0
nmi_sr:    .word 0
m_src:     .word 0
m_msg:     .word 0
m_sr:      .word 0
m_sp:      .word 0
m_count:   .word 0
swi128:    .word 0
ill2:      .word 0

s_title:   .asciz "RFC 0029 and RFC 0040 on the draft 2 CPU\n"
s_boot:    .asciz "boot state: "
s_vbr0:    .asciz "vbr after reset: "
s_spr:     .asciz "special registers: "
s_mapa:    .asciz "mapa: "
s_mapd:    .asciz "map through mapd: "
s_window:  .asciz "the window: "
s_user:    .asciz "user mode, banks, MTUR, MFUR: "
s_swiflags: .asciz "SWI saves S = 0: "
s_exitflags: .asciz "handlers run with S, without I: "
s_priv:    .asciz "privileged instructions trap: "
s_privvec: .asciz "privilege violation vector: "
s_uflags:  .asciz "user MTSR ccr: "
s_fault:   .asciz "page fault, FSR: "
s_far:     .asciz "page fault, FAR: "
s_retry:   .asciz "retried after mapping: "
s_wfault:  .asciz "store without W, FSR: "
s_wkept:   .asciz "store without W changed nothing: "
s_xfault:  .asciz "fetch without X, FSR: "
s_xpc:     .asciz "fetch fault saves its PC: "
s_range:   .asciz "user bit 31, and 16 MB-2 GB: "
s_sfault:  .asciz "supervisor page fault: "
s_mis:     .asciz "misaligned word, FAR, base kept: "
s_buserr:  .asciz "nothing answers, no trap: "
s_traps:   .asciz "divide, illegal, tag vectors: "
s_trace:   .asciz "trace: "
s_sr:      .asciz "MTSR sr keeps S: "
s_spl:     .asciz "SPL sets IPL alone; ccr: "
s_vbr:     .asciz "vbr, aligned, a second table: "
s_vbrswi:  .asciz "SWI through vbr: "
s_reqreg:  .asciz "request register set, read, clear: "
s_levels:  .asciz "levels above IPL, highest first: "
s_lvlipl:  .asciz "IPL in the handler, and saved: "
s_nest:    .asciz "nesting after EI: "
s_lvl78:   .asciz "levels 8 and 7: "
s_claim:   .asciz "message register claim: "
s_msg:     .asciz "message: source and 24 bits: "
s_msgsr:   .asciz "message level: M and IPL 7: "
s_msgsp:   .asciz "message level's own sp: "
s_msgr9:   .asciz "the kernel's registers kept: "
s_msgfree: .asciz "message register released: "
s_nmi:     .asciz "NMI over IPL 8, taken once: "
s_swi128:  .asciz "supervisor SWI #128: "
s_info:    .asciz "board information: "
s_timer:   .asciz "the timer counts: "
s_halt:    .asciz "HALT waits for the tick: "
s_done:    .asciz "done\n"
s_ok:      .asciz "ok\n"
s_want:    .asciz "want "
s_got:     .asciz " got "
        .align 2

        .include "../../v2_isa/programs/lib/console.s"
        .include "../../v2_isa/programs/lib/print.s"

; a second vector table for the vbr test: its illegal entry and SWI #1
        .align 2048
vtab2:  .org vtab2 + 0x08
        JMP  h_ill2
        .org vtab2 + 0x104
        JMP  h_swi1b
h_ill2: PUSH r1
        INC  [ill2]
        MOV  r1, [sp + 8]       ; past the ILLEGAL parcel
        ADD  r1, #2
        MOV  [sp + 8], r1
        POP  r1
        RTI
h_swi1b: INC [swi128]
        RTI
