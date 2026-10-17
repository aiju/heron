; hwiowait: the IOP's side of hw.py's check of the I/O bus's WAIT
; (RFC 0037, 18): the bench's WAIT cards in slots 2 and 3 with WAIT in
; their timing table entries. A write to slot 2 and a read of it, each
; held for 15 of CLKB's rises; event port register 1 then, in b; a read
; of slot 3, which holds WAIT as long as SEL, cut off by the bound, in c;
; register 1 with IOTO and device 3, in d; and cleared, in e.

.org 0
.reg a 8
.reg b 9
.reg c 10
.reg d 11
.reg e 12

start:  BANK <- #0
        X <- #0x0200            ; the WAIT cards: 0/3/0 (STROBE less one in bits 2-7) and WAIT
        F <- #(TT_WAIT | 2 << 2) | ttab <- F
        X <- #0x0300
        F <- #(TT_WAIT | 2 << 2) | ttab <- F
        X <- #0x0200
        F <- #0 | io <- F       ; D's upper byte 0, held for the reads
        AC <- io
        a <- AC
        AC <- ev1
        b <- AC
        X <- #0x0300
        AC <- io
        c <- AC
        AC <- ev1
        d <- AC
        F <- #0 | ev3 <- F      ; IOTO cleared, a clock later
        nop
        AC <- ev1
        e <- AC
done:   goto done
        nop
