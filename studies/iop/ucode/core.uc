; The IOP's microcode, part 1: reset, the inner interpreter, the task
; switch and the native layer (RFC 0027, 6.2-6.5). The primitives are in
; prims.uc. The notation is the microassembler's (uasm.py); the line after
; a branch is its delay slot, and always runs.

; ---- reset: uIR and uPC are cleared, and this runs from 0

.org 0
.reg np 3                       ; (the reset's registers, in bank 255)
.reg dst 4
.reg rx 5
.reg cnt 6
.reg pg 7
.reg cold 8

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

; The SRAM's self test, with nothing but AC, X and F: every cell its own
; address, then its complement, each read back, from the top down. A
; cell is tested for zero by writing it to the swap register and reading
; it back less one.
sramtest: AC <- #-1
        X <- AC
mt1:    [X] <- AC
        AC <- (ones & AC) - 1 | if carry goto mt1
        X <- AC
mt2:    F <- [X] ^ AC | swap <- F
        F <- swap - 1 | if carry goto memfail
        [X] <- ~AC
        AC <- (ones & AC) - 1 | if carry goto mt2
        X <- AC
mt3:    F <- [X] ^ ~AC | swap <- F
        F <- swap - 1 | if carry goto memfail
        nop
        AC <- (ones & AC) - 1 | if carry goto mt3
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

; The console task, bank 0: its registers through memory, then NEXT at
; the cold start's first cell.
        X <- #(BANKS + 64 * NATIVE_BANK + 8)
        BANK <- #CONSOLE_BANK
        F <- [X] - 1
        ip <- F
        sp <- #S0
        rp <- #R0
        resume <- #next
        link <- #CONSOLE_BANK
        wait <- #0
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

; A colon definition: X is its body, and ip the cell that named it.
nest:   rp, X <- rp - 1
        F <- ip
        [X] <- F | X <- F       ; push ip; X = ip
        F <- [X] | X <- F       ; the body
        ip <- F
        F <- [X] | X <- F | dispatch nest
        nop

ret_true:  AC <- #-1
        NEXT
ret_false: AC <- #0
        NEXT

; ---- attention: native work is waiting (the tick, a doorbell, WORK)

; From a primitive that has finished: ip is the cell it was. The common
; case is the tick with no INT line up: cleared, and straight on.
attn_next: F <- ev1 | ifnot F15 goto attn_slow
        F <- ev0 - 1            ; a line up?
        if carry goto attn_slow
        nop
        ev1 <- F | goto next1   ; only the tick: cleared
        ip, X <- ip + 1
attn_slow: tos <- AC | goto nat
        nret <- #fresume
fresume: AC <- tos | goto next1
        ip, X <- ip + 1

; The native layer runs in whatever bank is current, with AC free and
; registers 24-31 as its scratch, and goes back to nret. A tick with no
; INT line up is only cleared.
nat:    F <- ev1 | ifnot F15 goto nslow
        F <- ev0 - 1
        if carry goto nslow
        F <- nret
        ev1 <- F | goto F
        nop
nslow:  F <- ev1 | if F15 goto ntick
        X <- #EVMASK
        if bell goto nbell
        nop
        CTRL <- #CTRL_WORK      ; no native jobs yet: WORK off
        F <- nret | goto F
        nop

; The tick: route the INT lines that are up and enabled to the tasks that
; wait for them, and mask each until its task waits again.
ntick:  AC <- [X] | ev1 <- F    ; the enabled lines; the tick cleared
        ints <- ev0 & AC
        F <- ints - 1 | ifnot carry goto nat
        bit <- #1
        ex <- #(EVTAB - 1)
nroute: AC <- bit
        F <- (ints & AC) - 1 | ifnot carry goto nrnext
        ex, X <- ex + 1
        F <- [X] | X <- F       ; the owner's wait register
        [X] <- 0
        X <- #EVMASK
        [X] <- [X] & ~AC
        ints <- ints & ~AC
nrnext: F <- ints - 1 | ifnot carry goto nat
        bit <- bit + bit
        goto nroute
        nop

; Doorbells: for now, kept in BELLS for the Forth, and cleared one by one
; (RFC 0027, 4.4).
nbell:  bells <- ev2
        AC <- bells
        X <- #BELLS
        [X] <- [X] | AC
        bit <- #1
        ex <- #0
nbloop: AC <- bit
        F <- (bells & AC) - 1 | ifnot carry goto nbnext
        X <- ex
        ev2 <- F
nbnext: ex <- ex + 1
        bit <- bit + bit | ifnot carry goto nbloop
        nop
        goto nat
        nop

native_end:

; ---- tasks (RFC 0027, 6.4): a round robin through link, skipping those
; whose wait isn't 0, and looking at attention while it skips.

.org 0x8000
.prim pause
        tos <- AC
        F <- link | BANK <- F
ploop:  F <- wait - 1 | ifnot carry goto prun
        nop
        if attn goto pnat
        F <- link
        BANK <- F | goto ploop
        nop
pnat:   goto nat
        nret <- #ploop
prun:   F <- resume | goto F
        AC <- tos
