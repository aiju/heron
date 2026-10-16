; The IOP's microcode, part 1: reset, the inner interpreter, attention,
; the task switch and the native layer (RFC 0027, 6.2-6.5). jobs.uc has
; the native jobs (the movers, the clients' rings, posting events to the
; CPUs) and prims.uc the Forth's primitives. The notation is the
; microassembler's (uasm.py); the line after a branch is its delay slot,
; and always runs.
;
; m1, register 7, is -1 in every bank, so `BANK <- m1` goes to bank 255,
; the native layer's, while K holds a branch target.

; ---- reset: uIR and uPC are cleared, and this runs from 0

.org 0
.reg np 0                       ; (the reset's registers, in bank 255)
.reg dst 1
.reg rx 2
.reg cnt 3
.reg pg 4
.reg cold 5

reset:  BANK <- #NATIVE_BANK
        X <- #0x0C00            ; the timing table: the card's own devices
        F <- #TT_UART | ttab <- F
        X <- #0x0D00
        F <- #TT_FLASH | ttab <- F
        X <- #0x0E00
        F <- #TT_TIMER | ttab <- F
        X <- #0x0F00
        F <- #TT_PORTS | ttab <- F
        F <- #1 | io <- F       ; the LEDs: 1, alive

; The SRAM's self test, with nothing but AC, X and F, as the registers are
; in the SRAM too: every cell its own address, then its complement, each
; read back. AC counts up, and its carry out of 0xFFFF, held into the
; next microinstruction, ends a pass.
sramtest: AC <- #0
        X <- AC
mt1:    [X] <- AC
        AC <- #1 + AC
        ifnot carry goto mt1
        X <- AC
mt2:    F <- [X] ^ AC | swap <- F       ; 0 if the cell held its address
        F <- swap - 1 | if carry goto memfail
        [X] <- ~AC
        AC <- #1 + AC
        ifnot carry goto mt2
        X <- AC
mt3:    F <- [X] ^ ~AC | swap <- F
        F <- swap - 1 | if carry goto memfail
        nop
        AC <- #1 + AC
        ifnot carry goto mt3
        X <- AC

; The dictionary, out of the image flash: whole pages of 256 halfwords
; from FL_DICT on, to the SRAM from 0.
dictcopy: F <- #0 | pg1 <- F    ; the header, in page 0
        X <- #(0x0D00 + FL_PAGES)
        np <- io
        X <- #(0x0D00 + FL_COLD)
        AC <- io
        cold <- AC
        X <- #(0x0D00 + FL_MAGIC)
        AC <- io
        F <- #FLASH_MAGIC ^ AC | swap <- F
        F <- swap - 1 | if carry goto noimage
        np <- np - 1            ; (delay) pages less one
        dst <- #-1
        pg <- #(FL_DICT >> 8)
cpage:  F <- pg
        pg1 <- F
        rx <- #0x0CFF
        cnt <- #255
        rx, X <- rx + 1
ccell:  AC <- io
        dst, X <- dst + 1
        [X] <- AC
        cnt <- cnt - 1 | if carry goto ccell
        rx, X <- rx + 1
        pg <- pg + 1
        np <- np - 1 | if carry goto cpage
        nop

; The system variables, zeroed: no jobs, no sources routed, no rings.
        dst <- #DICT_END
        X <- #DICT_END
        cnt <- #255
zcell:  [X] <- 0
        cnt <- cnt - 1 | if carry goto zcell
        dst, X <- dst + 1
        X <- #TICKS
        AC <- #TICKS_IDLE
        [X] <- AC
        m1 <- #-1
        nturnc <- #(TURN_TICKS - 1)

; The console task, bank 0: its registers, then NEXT at the cold start's
; first cell.
        X <- #(BANKS + 64 * NATIVE_BANK + 5)
        BANK <- #CONSOLE_BANK
        F <- [X] - 1
        ip <- F
        sp <- #S0
        rp <- #R0
        resume <- #next
        link <- #CONSOLE_BANK
        wait <- #0
        m1 <- #-1
        me <- #CONSOLE_BANK
        up <- #(BANKS + 64 * CONSOLE_BANK)
        X <- #0x0F00            ; the LEDs: 3, running Forth
        F <- #3 | io <- F
        goto next
        nop

memfail: X <- #0x0F00           ; the LEDs: E1, the SRAM is broken
        F <- #0xE1 | io <- F
halt:   goto halt
        nop
noimage: X <- #0x0F00           ; the LEDs: E2, no Forth in the flash
        F <- #0xE2 | io <- F
        goto halt
        nop

; ---- the inner interpreter (RFC 0027, 6.2)

next:   ip, X <- ip + 1
next1:  F <- [X] | X <- F | dispatch nest
        nop

; A colon definition: ip is the cell that named it.
nest:   rp, X <- rp - 1
        F <- ip
        [X] <- F | X <- F       ; push ip; X = ip
        F <- [X] | X <- F       ; the body
        ip <- F
        F <- [X] | X <- F | dispatch nest
        nop

; nest-w: a colon definition `execute` runs, at w; ip is execute's cell.
nestw:  rp, X <- rp - 1
        F <- ip
        [X] <- F                ; push ip
        F <- w | X <- F         ; the body
        ip <- F
        F <- [X] | X <- F | dispatch nest
        nop

ret_true:  AC <- #-1
        NEXT
ret_false: AC <- #0
        NEXT

; ---- attention: native work is waiting (the tick, a doorbell, WORK)

; From a primitive that has finished: ip is the cell it was. The common
; case is the tick with no INT line up: TICKS counted down, the tick
; cleared, and straight on, unless held levels are due.
attn_next: F <- ev1 | ifnot F15 goto attn_slow    ; not the tick: a doorbell, or WORK
        X <- #TICKS
        F <- ev0 - 1 | if carry goto attn_line    ; an INT line is up
        [X] <- [X] - 1                             ; (delay) the countdown
        ev1 <- F | if carry goto next1             ; the tick cleared; on, unless it ran out
        ip, X <- ip + 1
        ip <- ip - 1            ; held levels are due: back to the finished cell
        tos <- AC
        BANK <- m1 | goto ndue
        nret <- #ret_task
attn_slow: tos <- AC
        BANK <- m1 | goto nloop
        nret <- #ret_task
attn_line: tos <- AC            ; X is TICKS, counted down
        BANK <- m1 | goto ntick2
        nret <- #ret_task

; Back from the native layer: X is CURTASK.
ret_task: F <- [X] | BANK <- F
        ip, X <- ip + 1 | goto next1
        AC <- tos

; ---- the native layer (RFC 0027, 6.4), in bank 255: the tick, the
; doorbells, and the jobs' slices, the head of their queue first. It goes
; back to nret, with X at CURTASK. A job's turn lasts TURN_TICKS ticks;
; then the queue moves on and the Forth gets a turn.

nloop:  F <- ev1 | if F15 goto ntick
        X <- #JQHEAD
        if bell goto nbell
        F <- [X] - 1
        if carry goto nrun
        nop
        CTRL <- #CTRL_WORK      ; nothing to do: WORK off
        F <- nret | goto F
        X <- #CURTASK

nrun:   F <- nturnf - 1 | if carry goto nrot   ; the turn is over
        nop
        F <- [X] | BANK <- F    ; the job at the head
        F <- jres | goto F
        CTRL <- #CTRL_WORK      ; WORK off while it runs: attention is the tick and doorbells

; The head job's turn is over: it goes to the back, and the Forth gets a
; turn, with WORK on so that the jobs come back.
nrot:   nturnf <- #0
        AC <- [X]               ; the head
        X <- #JQTAIL
        [X] <- AC
        X <- #JLINK + AC
        AC <- [X]
        X <- #JQHEAD
        [X] <- AC
        CTRL <- #(8 | CTRL_WORK)
        F <- nret | goto F
        X <- #CURTASK

; A job's slice found attention: to the native layer, and back to it at
; jres.
jattn:  BANK <- m1 | goto nloop
        nop

; A job leaves the queue, from its head.
jstop:  BANK <- m1
        X <- #JQTAIL
        AC <- [X]
        X <- #JQHEAD
        AC <- [X] ^ AC
        F <- m1 + AC | ifnot carry goto js_last    ; it was the only one
        AC <- [X]
        X <- #JLINK + AC
        F <- [X]
        t0 <- F                 ; its successor
        [X] <- 0                ; not queued
        X <- #JQTAIL
        AC <- [X]
        X <- #JLINK + AC
        AC <- t0
        [X] <- AC               ; the tail's successor
        X <- #JQHEAD
        [X] <- AC | goto nloop
        nop
js_last: X <- #JLINK + AC
        [X] <- 0
        X <- #JQHEAD
        [X] <- 0 | goto nloop
        nop

; Enqueue the job in bank AC, which isn't queued, at the back. t0 and t1
; are scratch; back to t7.
jenq:   t0 <- AC
        X <- #JQHEAD
        F <- [X] - 1 | ifnot carry goto jq_empty
        AC <- [X]
        t1 <- AC                ; the head
        AC <- t0
        X <- #JLINK + AC
        AC <- t1
        [X] <- AC               ; its successor: the head
        X <- #JQTAIL
        AC <- [X]
        X <- #JLINK + AC
        AC <- t0
        [X] <- AC               ; the tail's: it
        X <- #JQTAIL
        [X] <- AC
        F <- t7 | goto F
        nop
jq_empty: AC <- t0
        X <- #JLINK + AC
        [X] <- AC               ; a ring of one
        X <- #JQHEAD
        [X] <- AC
        X <- #JQTAIL
        [X] <- AC
        F <- t7 | goto F
        nop

; ---- the tick: held levels when TICKS runs out, the INT lines and
; ATN0-3 that are up and enabled to their owners, each masked until it
; has been served. Every TURN_TICKS ticks the running job's turn ends.

ntick:  X <- #TICKS
        [X] <- [X] - 1
ntick2: ev1 <- F                ; the tick cleared
        F <- [X] + 1 | if carry goto ndue      ; TICKS ran out
        nop
nturn:  nturnc <- nturnc - 1 | if carry goto nlines
        nop
        nturnc <- #(TURN_TICKS - 1)
        nturnf <- #1

nlines: AC <- ev0
        X <- #EVMASK
        AC <- [X] & AC          ; up and enabled
        F <- m1 + AC | ifnot carry goto natn
        nint <- AC
        [X] <- [X] & ~AC        ; masked until served
        nwhich <- #natn
        AC <- #1
        nsrc <- #SRC_ATN        ; the bits come out from the top: INT 15 first
nl_loop: nint <- nint + nint | ifnot carry goto nl_loop
        nsrc <- nsrc - AC
        goto nroute
        t7 <- #nl_back
nl_back: AC <- #1
        F <- nint - 1 | if carry goto nl_loop
        nop
        F <- nwhich | goto F
        nop

natn:   AC <- ev1
        X <- #ATNMASK
        AC <- [X] & AC
        F <- m1 + AC | ifnot carry goto nloop
        F <- AC | swap <- F     ; (delay) bits 0-3 to 8-11
        [X] <- [X] & ~AC
        AC <- swap
        nint <- AC
        nint <- nint + nint
        nint <- nint + nint
        nint <- nint + nint
        nint <- nint + nint     ; bits 12-15
        nwhich <- #nloop
        AC <- #1
        goto nl_loop
        nsrc <- #(SRC_ATN + 4)

; Source nsrc to its owner (EVTAB): a task's wait register cleared, or an
; event to a CPU. Back to t7.
nroute: AC <- nsrc
        AC <- nsrc + AC
        t6 <- AC
        AC <- t6 + AC
        t6 <- #EVTAB + AC       ; the source's entry
        X <- t6
        AC <- [X]               ; the owner
        F <- AC | if F15 goto nr_task
        X <- AC
        F <- m1 + AC | ifnot carry goto nr_none
        F <- nsrc
        t0 <- F                 ; the event: the source's number
        t6, X <- t6 + 1
        F <- [X]
        t1 <- F                 ; 16 x the CPU
        t6, X <- t6 + 1
        F <- [X]
        t2 <- F                 ; the level
        t6, X <- t6 + 1
        F <- [X]
        t3 <- F | goto post     ; the hold
        nop
nr_task: [X] <- 0 | goto nr_none
        nop
nr_none: F <- t7 | goto F
        nop

; Held levels are due: each CPU's, at once; TICKS back to idle.
ndue:   X <- #TICKS
        AC <- #TICKS_IDLE
        [X] <- AC
        nsrc <- #(EVRING + E_PEND - 16)
        nint <- #(CPUS - 1)
nd_cpu: AC <- #16
        nsrc, X <- nsrc + AC
        F <- [X] - 1 | ifnot carry goto nd_next     ; none held
        AC <- [X]
        [X] <- 0
        F <- nsrc - 1 | X <- F                      ; E_SEG
        AH0 <- [X]
        CTRL <- #(8 | CTRL_SESSION)
        F <- AC | AB <- F
        F <- #IRQ_SET | wr.h AH0
        CTRL <- #CTRL_SESSION
nd_next: nint <- nint - 1 | if carry goto nd_cpu
        nop
        goto nturn
        nop

; ---- doorbells (RFC 0027, 7.1): each one rung cleared, and its client's
; ring job queued if it isn't. A doorbell with no ring goes to BELLS, for
; the Forth.

nbell:  AC <- ev2
        nint <- AC
        nsrc <- #0
        nbit <- #1
nb_loop: AC <- nbit
        F <- (nint & AC) - 1 | ifnot carry goto nb_next
        X <- nsrc
        ev2 <- F                ; doorbell X[3:0] cleared
        nint <- nint & ~AC
        X <- #CLIENTS
        F <- ([X] & AC) - 1 | ifnot carry goto nb_none
        AC <- nsrc
        X <- #(JLINK + CLIENT_BANK) + AC
        F <- [X] - 1 | if carry goto nb_next       ; queued already
        AC <- #CLIENT_BANK + AC
        t7 <- #nb_next
        goto jenq
        nop
nb_none: AC <- nbit
        X <- #BELLS
        [X] <- [X] | AC
nb_next: F <- nint - 1 | ifnot carry goto nloop    ; none left
        nsrc <- nsrc + 1
        goto nb_loop
        nbit <- nbit + nbit

native_end:

; ---- tasks (RFC 0027, 6.4): a round robin through link, skipping those
; whose wait isn't 0, and looking at attention while it skips.

.org 0x8000
.prim pause
xpause: tos <- AC
pause1: F <- link | BANK <- F
ploop:  F <- wait - 1 | ifnot carry goto prun
        X <- #CURTASK
        if attn goto pnat
        F <- link
        BANK <- F | goto ploop
        nop
prun:   F <- me
        [X] <- F
        F <- resume | goto F
        AC <- tos
pnat:   F <- me
        [X] <- F                ; the task to look at again
        BANK <- m1 | goto nloop
        nret <- #ret_pause
ret_pause: F <- [X] | BANK <- F | goto ploop
        nop
