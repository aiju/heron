; devices: Heron Mini's I/O devices, for the chip-level netlist (board.py's
; io_space). Everything goes to UART 0 except one line to UART 1:
;
;  1. both UARTs set up: 115200 baud from 1.8432 MHz, 8N1, FIFOs, polled
;  2. the boot flash: a string after its (empty) header
;  3. the CF card: its status after reset, and READ SECTORS of sector 3
;     with 16-bit transfers, checked against the pattern the simulation
;     preloads (sector n: "sector n", a NUL, then (n + i) mod 256)
;  4. the 82C54: counter 0 as a rate generator, three interrupts through
;     the timer's flag, the interrupt status as the first one finds it
;  5. the control register (the speaker and the LEDs), written
;  6. UART 0's input echoed, up to the terminal's ^D
;
; Nothing printed depends on how long anything takes. The 82C54 needs
; 165 ns between accesses, so its stores are spaced by other instructions.
; Calls write the return address into r7 (RFC 0028, 5.7): a routine that
; calls saves it.

        .org 0x00
        JMP  start              ; reset
        .org 0x04
        JMP  isr                ; IRQ
        .org 0x08
        JMP  fatal              ; illegal instruction
        .org 0x0C
        JMP  fatal              ; SWI
        .org 0x10
        JMP  fatal              ; divide error
        .org 0x14
        JMP  fatal              ; address error
        .org 0x18
        JMP  fatal              ; tag check
        .org 0x1C

UART0    = 0xE0000000           ; region 6, registers a word apart
UART1    = 0xE0000020           ; A5 high
U_IER    = 0x04
U_FCR    = 0x08
U_LCR    = 0x0C
U_MCR    = 0x10
U_LSR    = 0x14
CF       = 0x80000000           ; region 0: the task file (CS0)
CF_CTRL  = 0x80000038           ; the control block (CS1) register 6
PIT      = 0xB0000000           ; region 3: counters 0-2, then the control word
FLASH    = 0xD0000000           ; region 5: a byte a word
LOCAL    = 0xF0000000           ; region 7: the on-board registers
L_STATUS = 0x800                ; R: interrupt status  W: the timer's acknowledge
L_CTRL   = 0xC00                ; the control register

PERIOD   = 1843                 ; 1 ms of 1.8432 MHz

start:  MOV  sp, #0x100000
        MOV  r1, #UART0
        BSR  uinit
        MOV  r1, #UART1
        BSR  uinit
        CALL main
        MOV  r9, #UART0
        BSR  flush
        MOV  r9, #UART1
        BSR  flush
        DI
        HALT

; isr: the timer (nothing else is enabled). Keep the first status seen,
; acknowledge, count.
isr:    SAVE r1-r3
        MOV  r2, #LOCAL
        MOV  r1, byte [r2 + L_STATUS]
        MOVS r3, [status]
        BPL  .seen
        MOV  [status], r1
.seen:  CLR  byte [r2 + L_STATUS]
        INC  [ticks]
        RESTORE r1-r3
        RTI

fatal:  MOV  r9, #UART0
        LEA  r1, [s_fatal]
        BSR  uputs
        BSR  flush
        DI
        HALT

main:   SAVE r7-r11
        MOV  r9, #UART0
        LEA  r1, [s_title]
        BSR  uputs

        ; ---- the boot flash: bytes 4 on, a NUL-terminated string ----
        LEA  r1, [s_flash]
        BSR  uputs
        MOV  r11, #FLASH + 16
.fl:    MOVS r1, byte [r11]
        BEQ  .fldone
        BSR  uputc
        ADD  r11, #4
        BRA  .fl
.fldone:

        ; ---- the CF card ----
        MOV  r11, #CF
        MOV  r1, #0x02          ; nIEN: no interrupts
        MOV  r2, #CF_CTRL
        MOV  byte [r2], r1
        BSR  cfwait
        LEA  r1, [s_cf]
        BSR  uputs
        MOV  r1, byte [r11 + 0x1C]
        BSR  hex2
        MOV  r1, #1
        MOV  byte [r11 + 0x08], r1       ; count
        MOV  r1, #3
        MOV  byte [r11 + 0x0C], r1       ; LBA 7-0
        CLR  byte [r11 + 0x10]
        CLR  byte [r11 + 0x14]
        MOV  r1, #0xE0
        MOV  byte [r11 + 0x18], r1       ; LBA mode, device 0
        MOV  r1, #0x20
        MOV  byte [r11 + 0x1C], r1       ; READ SECTORS
        BSR  cfwait
.drq:   MOV  r1, byte [r11 + 0x1C]
        AND  r1, #0x08          ; DRQ
        BEQ  .drq
        LEA  r8, [buf]
        MOV  r10, #256
.rd:    MOV  r1, half [r11]
        MOV  half [r8], r1
        ADD  r8, #2
        DEC  r10
        BNE  .rd
        LEA  r1, [s_q]
        BSR  uputs
        LEA  r1, [buf]
        BSR  uputs
        LEA  r1, [s_q]
        BSR  uputs
        ; bytes 9 on: (3 + i) mod 256
        MOV  r8, #9
.chk:   LEA  r1, [buf]
        MOV  r1, byte [r1 + r8]
        MOV  r2, r8
        ADD  r2, #3
        AND  r2, #0xFF
        CMP  r1, r2
        BNE  .bad
        INC  r8
        CMP  r8, #512
        BLO  .chk
        LEA  r1, [s_ok]
        BRA  .cfdone
.bad:   LEA  r1, [s_bad]
.cfdone:
        BSR  uputs

        ; ---- the 82C54 ----
        MOV  r11, #PIT
        MOV  r1, #-1
        MOV  [status], r1
        CLR  [ticks]
        MOV  r1, #0x34          ; counter 0: LSB then MSB, mode 2, binary
        MOV  byte [r11 + 0x0C], r1
        MOV  r1, #PERIOD & 0xFF
        MOV  byte [r11], r1
        MOV  r1, #PERIOD >> 8
        MOV  byte [r11], r1
        EI
.tick:  MOV  r1, [ticks]
        CMP  r1, #3
        BLO  .tick
        DI
        LEA  r1, [s_timer]
        BSR  uputs
        MOV  r1, [ticks]
        ADD  r1, #'0'
        BSR  uputc
        LEA  r1, [s_status]
        BSR  uputs
        MOV  r1, [status]
        BSR  hex2

        ; ---- the control register: speaker gate and data, LED 1 ----
        MOV  r11, #LOCAL
        MOV  r1, #0x0B
        MOV  byte [r11 + L_CTRL], r1

        ; ---- UART 1 ----
        MOV  r9, #UART1
        LEA  r1, [s_uart1]
        BSR  uputs

        ; ---- UART 0's input, echoed ----
        MOV  r9, #UART0
        LEA  r1, [s_echo]
        BSR  uputs
.in:    MOV  r1, byte [r9 + U_LSR]
        AND  r1, #0x01          ; DR
        BEQ  .in
        MOV  r1, byte [r9]
        CMP  r1, #4             ; ^D
        BEQ  .indone
        BSR  uputc
        BRA  .in
.indone:
        RESTORE r7-r11
        RET

; uinit: r1 = a UART's base. 115200 baud (divisor 1), 8N1, FIFOs on,
; polled; DTR, RTS and auto flow control on, so the terminal sends.
uinit:  MOV  r2, #0x80
        MOV  byte [r1 + U_LCR], r2      ; DLAB
        MOV  r2, #1
        MOV  byte [r1], r2              ; DLL
        CLR  byte [r1 + U_IER]          ; DLM
        MOV  r2, #0x03
        MOV  byte [r1 + U_LCR], r2      ; 8N1
        MOV  r2, #0x07
        MOV  byte [r1 + U_FCR], r2      ; FIFOs on and cleared
        CLR  byte [r1 + U_IER]          ; polled
        MOV  r2, #0x23
        MOV  byte [r1 + U_MCR], r2      ; DTR, RTS, auto flow control
        RET

; uputc: r1 = a character, to the UART at r9. Clobbers r3.
uputc:  MOV  r3, byte [r9 + U_LSR]
        AND  r3, #0x20          ; THRE: room in the transmit FIFO
        BEQ  uputc
        MOV  byte [r9], r1
        RET

; uputs: r1 = a string, to the UART at r9. Clobbers r1, r3, r4.
uputs:  SAVE r7
        MOV  r4, r1
.next:  MOVS r1, byte [r4]+
        BEQ  .done
        BSR  uputc
        BRA  .next
.done:  RESTORE r7
        RET

; flush: wait until the UART at r9 has sent everything.
flush:  MOV  r3, byte [r9 + U_LSR]
        AND  r3, #0x40          ; TEMT
        BEQ  flush
        RET

; hex2: r1's low byte as two hex digits, then a newline. Clobbers r1-r3.
hex2:   SAVE r7
        MOV  r2, r1
        LSR  r1, #4
        AND  r1, #0x0F
        BSR  hexd
        MOV  r1, r2
        AND  r1, #0x0F
        BSR  hexd
        RESTORE r7
        MOV  r1, #10
        BRA  uputc
hexd:   CMP  r1, #10
        BLO  .dig
        ADD  r1, #'A' - '0' - 10
.dig:   ADD  r1, #'0'
        BRA  uputc

; cfwait: until the CF card at r11 isn't busy. Clobbers r1.
cfwait: MOV  r1, byte [r11 + 0x1C]
        AND  r1, #0x80          ; BSY
        BNE  cfwait
        RET

s_title:  .asciz "Heron Mini devices\n"
s_flash:  .asciz "boot flash: "
s_cf:     .asciz "cf: status "
s_q:      .asciz "\""
s_ok:     .asciz ", ok\n"
s_bad:    .asciz ", bad\n"
s_timer:  .asciz "timer: "
s_status: .asciz " interrupts, status "
s_uart1:  .asciz "uart 1\n"
s_echo:   .asciz "echo: "
s_fatal:  .asciz "TRAP\n"
        .align 4
status: .word 0
ticks:  .word 0
buf:    .space 512
