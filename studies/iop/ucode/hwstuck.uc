; hwstuck: the IOP's side of hw.py's check of the stuck-transfer counter:
; a read from the bench's stuck slave, which holds WAIT until the counter
; asserts RESET; then the event port's register 1 with STUCK and OWN in
; a, cleared, in b. A second read, of the bench's RAM, as it should be,
; in c.

.org 0
.reg a 8
.reg b 9
.reg c 10

start:  BANK <- #0
        AH0 <- #0x5000          ; as bus@ does it: the session, then the read
        CTRL <- #(8 | CTRL_SESSION)
        AH1 <- #0
        F <- #0 | rd.h AH0      ; the stuck slave
        F <- #0
        AC <- BA                ; waits for the data phase's end
        CTRL <- #CTRL_SESSION
        CTRL <- #(8 | CTRL_SESSION)
        AC <- ev1
        a <- AC
        F <- #0 | ev3 <- F      ; STUCK and OWN cleared
        AC <- ev1
        b <- AC
        F <- #0x1234 | AB <- F
        F <- #0x0100 | wr.h AH1
        F <- #0x0100 | rd.h AH1
        AC <- BA
        c <- AC
        CTRL <- #CTRL_SESSION
done:   goto done
        nop
