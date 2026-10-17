; hwtest: a microcode program of its own, for checking the netlist
; (card.py) against the model where the Forth's firmware would take long
; to get to, or the timer's ticks would make the two part (hw.py's
; check_ucode): the system bus side, the shared RAM, the swap and page
; registers, the I/O bus, each a few ways. It ends in `done`, with what it
; read in a and onward, and in the CPU card's RAM.

.org 0
.reg a 8
.reg b 9
.reg c 10
.reg d 11
.reg e 12
.reg f 13
.reg g 14
.reg h 15

start:  BANK <- #0
        X <- #0x0C00            ; the timing table: the console, the flash, the timer, the ports
        F <- #TT_UART | ttab <- F
        X <- #0x0D00
        F <- #TT_FLASH | ttab <- F
        X <- #0x0E00
        F <- #TT_TIMER | ttab <- F
        X <- #0x0F00
        F <- #TT_PORTS | ttab <- F
        F <- #5 | io <- F       ; the LEDs

; the system bus: the session, then halfwords from F, one after another,
; each AB load waiting for the last write
        CTRL <- #(8 | CTRL_SESSION)
        AH0 <- #0
        AH1 <- #0
        F <- #0x1234 | AB <- F
        F <- #0x0100 | wr.h AH0
        F <- #0x5678 | AB <- F
        F <- #0x0102 | wr.h AH0
        F <- #0x9ABC | AB <- F
        F <- #0x0104 | wr.h AH1
; read back onto R, through BA
        F <- #0x0102 | rd.h AH0
        AC <- BA
        a <- AC
        F <- #0x0100 | rd.h AH0
        F <- #0x0104 | rd.h AH0 ; back to back: the second waits at E1
        AC <- BA
        b <- AC
; a copy: AB <- BA with the write
        F <- #0x0100 | rd.h AH0
        F <- #0x0200 | AB <- BA | wr.h AH1
        F <- #0x0102 | rd.h AH0
        F <- #0x0202 | AB <- BA | wr.h AH1
; bytes
        F <- #0xCD00 | AB <- F
        F <- #0x0301 | wr.b1 AH0
        F <- #0x00EF | AB <- F
        F <- #0x0300 | wr.b0 AH0
        F <- #0x0300 | rd.h AH0
        AC <- BA
        c <- AC
; nobody there: one data clock, and D as it was
        AH1 <- #0x6000
        F <- #0x0000 | rd.h AH1
        AC <- BA
        d <- AC
        CTRL <- #CTRL_SESSION

; the shared RAM, the swap register, the page register
        F <- #3 | pg0 <- F
        X <- #0x0010
        F <- #0xA55A | sr <- F
        X <- #0x0012
        F <- #0x0FF0 | sr <- F
        X <- #0x0010
        AC <- sr
        F <- AC | swap <- F
        AC <- swap
        e <- AC

; the I/O bus: the UART's scratch register, the flash's header, a read
; into AB with a write on the system bus in the same microinstruction
        X <- #0x0C07
        F <- #0x5A | io <- F
        AC <- io
        f <- AC
        F <- #0 | pg1 <- F
        X <- #(0x0D00 + FL_MAGIC)
        AC <- io
        g <- AC
        CTRL <- #(8 | CTRL_SESSION)
        AH0 <- #0
        X <- #(0x0D00 + FL_PAGES)
        F <- #0x0400 | AB <- io | wr.h AH0
        F <- #0x0400 | rd.h AH0
        AC <- BA
        h <- AC
        CTRL <- #CTRL_SESSION

done:   goto done
        nop
