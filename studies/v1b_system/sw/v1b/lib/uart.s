; The console's primitives for the system (draft 1b on the system bus): the
; I/O card's UART (studies/v1b_system/iocard.py). lib/start.s includes this;
; lib/console.s builds the usual console routines on it.
;
;   __con_init                       set up the UART              clobbers r1
;   __con_putc   r1 = character      wait for room, send it       clobbers nothing
;   __con_getc                       -> r1 = byte, or -1 at the end of input;
;                                       N and Z from r1           clobbers nothing else
;   __con_flush                      wait until everything is sent  clobbers r1
;
; The end of the input is the terminal's ^D (EOT, 4): after it every read
; returns -1.

UART     = 0xFFFFFFC0           ; the I/O card in slot 15: 16C550 registers 4 apart
U_DATA   = UART + 0x00          ; RBR / THR
U_IER    = UART + 0x04
U_FCR    = UART + 0x08
U_LCR    = UART + 0x0C
U_MCR    = UART + 0x10
U_LSR    = UART + 0x14
U_DLL    = UART + 0x00          ; with LCR.7 set
U_DLM    = UART + 0x04

        .align 2

; 921600 baud from the 14.7456 MHz clock (divisor 1), 8 data bits, no
; parity, 1 stop bit; FIFOs on; DTR, RTS and auto flow control on, so the
; terminal waits while the receive FIFO is full.
__con_init:
        MOV  r1, #0x80
        ST   r1, byte [U_LCR]   ; DLAB
        MOV  r1, #1
        ST   r1, byte [U_DLL]
        ST   r0, byte [U_DLM]
        MOV  r1, #0x03
        ST   r1, byte [U_LCR]   ; 8N1, DLAB off
        MOV  r1, #0x07
        ST   r1, byte [U_FCR]   ; FIFOs on and cleared, trigger level 1
        ST   r0, byte [U_IER]   ; polled
        MOV  r1, #0x23
        ST   r1, byte [U_MCR]   ; DTR, RTS, auto flow control
        ST   r0, byte [__con_eof]
        RET

__con_putc:
        PUSH r2
.wait:  MOV  r2, byte [U_LSR]
        AND  r2, #0x20          ; THRE: room in the transmit FIFO
        BEQ  .wait
        ST   r1, byte [U_DATA]
        POP  r2
        RET

__con_getc:
        MOV  r1, byte [__con_eof]
        BNE  .eof
.wait:  MOV  r1, byte [U_LSR]
        AND  r1, #0x01          ; DR: a byte has arrived
        BEQ  .wait
        MOV  r1, byte [U_DATA]
        CMP  r1, #4             ; ^D: the end of the input
        BEQ  .end
        TST  r1, r1             ; N clear, Z for a NUL byte
        RET
.end:   MOV  r1, #1
        ST   r1, byte [__con_eof]
.eof:   MOV  r1, #-1
        RET

__con_flush:
        MOV  r1, byte [U_LSR]
        AND  r1, #0x40          ; TEMT: the transmitter is empty
        BEQ  __con_flush
        RET

__con_eof:
        .byte 0
        .align 2
