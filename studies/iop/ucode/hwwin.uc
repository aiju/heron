; hwwin: the IOP's side of hw.py's check of the window: it fills in the
; timing table, then reads the flash's header and writes the LEDs in a
; loop, 100 passes, so that the window's accesses from the bench's second
; master find the I/O bus busy and the core's find the window's in the
; way. It ends in `done`, the sum of the halfwords it read in e, a last
; one in a.

.org 0
.reg a 8
.reg d 11
.reg e 12

start:  BANK <- #0
        X <- #0x0C00            ; the timing table: the console, the flash, the timer, the ports
        F <- #TT_UART | ttab <- F
        X <- #0x0D00
        F <- #TT_FLASH | ttab <- F
        X <- #0x0E00
        F <- #TT_TIMER | ttab <- F
        X <- #0x0F00
        F <- #TT_PORTS | ttab <- F
        F <- #0 | pg1 <- F
        e <- #0
        d <- #99
loop:   X <- #(0x0D00 + FL_MAGIC)
        AC <- io
        AC <- e + AC
        e <- AC
        X <- #0x0F00
        AC <- d
        F <- AC | io <- F       ; the LEDs
        d <- d - 1 | if carry goto loop
        nop
        X <- #(0x0D00 + FL_PAGES)
        AC <- io
        a <- AC
done:   goto done
        nop
