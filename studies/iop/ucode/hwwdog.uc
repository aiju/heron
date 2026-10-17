; hwwdog: the IOP's side of hw.py's check of the watchdog: it counts its
; starts in a, which COLD leaves as it was, kicks the watchdog 4 times
; and stops kicking. Then the watchdog should end the wait with COLD, and
; the program start again.

.org 0
.reg a 8

start:  BANK <- #0
        a <- a + 1
        X <- #0x0F00
        F <- #TT_PORTS | ttab <- F
        X <- #0x0F01
        LC <- #-4
kick:   F <- #1 | io <- F
        F <- #0 | io <- F
        F <- #0 | io <- F
        if lc goto kick
        F <- #0 | io <- F
done:   goto done
        nop
