; hwslave: the IOP's side of hw.py's check of the slave side, against a
; second master on the bench: it waits for doorbell 3, clears it, adds the
; two halfwords the master wrote at 0x100 and 0x102 of the shared RAM and
; writes the sum at 0x200, then reads the shared RAM in a loop, so that
; the master's next accesses find the core using T. It ends in `done`,
; the doorbells as it found them in a, the halfwords in b and c.

.org 0
.reg a 8
.reg b 9
.reg c 10
.reg d 11

start:  BANK <- #0
wait:   if bell goto got
        nop
        goto wait
        nop
got:    AC <- ev2               ; which doorbells
        a <- AC
        X <- #3
        F <- #0 | ev2 <- F      ; doorbell 3 cleared
        F <- #0 | pg0 <- F
        X <- #0x0100
        AC <- sr
        b <- AC
        X <- #0x0102
        AC <- sr
        c <- AC
        AC <- b
        AC <- c + AC
        X <- #0x0200
        F <- AC | sr <- F       ; the sum
        LC <- #0
        X <- #0x0100
spin:   AC <- sr | if lc goto spin
        d <- AC
        LC <- #0
spin2:  F <- AC | sr <- F | if lc goto spin2
        AC <- sr
done:   goto done
        nop
