; cfcard: the I/O card's CompactFlash card, in True IDE mode with 8-bit
; data transfers (the I/O card has the card's D0-D7 only). The card starts
; as programs.cf_disk() makes it: sector n holds the text "sector n" and a
; NUL, then the bytes (n + i) mod 256 to its end.
;
;  1. the task file as the bus reset leaves it (the diagnostic signature)
;  2. SET FEATURES 01h: 8-bit data transfers
;  3. IDENTIFY DEVICE: the model, the serial number, the firmware, the size
;  4. READ SECTORS, polled: two sectors, and the card's last sector,
;     checked against the pattern
;  5. WRITE SECTORS, polled: three sectors, read back and compared
;  6. READ VERIFY, a read past the end of the card (IDNF) and a command
;     the card doesn't know (ABRT)
;  7. READ SECTORS and WRITE SECTORS driven by the card's interrupt (IRQ1),
;     sleeping with HALT until it comes
;
; Nothing printed depends on how long anything takes; the sectors written
; are compared with the instruction-level model's card afterwards.

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
        JMP  fatal              ; address error, bus error
        .org 0x18

CF       = 0xFFFFFF80           ; the task file (CS0), registers 4 apart
CF_DATA  = CF + 0x00
CF_ERR   = CF + 0x04            ; R: error  W: features
CF_FEAT  = CF + 0x04
CF_COUNT = CF + 0x08
CF_LBA0  = CF + 0x0C
CF_LBA1  = CF + 0x10
CF_LBA2  = CF + 0x14
CF_HEAD  = CF + 0x18            ; drive/head: LBA, device, LBA bits 24-27
CF_STAT  = CF + 0x1C            ; R: status (acknowledges the interrupt)
CF_CMD   = CF + 0x1C            ; W: command
CF_ALT   = 0xFFFFFF58           ; the control block (CS1) register 6: R: the
CF_CTRL  = 0xFFFFFF58           ; alternate status  W: device control

BSY      = 0x80
DRQ      = 0x08
NIEN     = 0x02                 ; device control: no interrupts

C_READ   = 0x20
C_WRITE  = 0x30
C_VERIFY = 0x40
C_IDENT  = 0xEC
C_FEAT   = 0xEF
C_NOP    = 0x00                 ; not a command this card knows

SECTORS  = 2048                 ; on the card
BUF      = 0x40000              ; sectors read
WBUF     = 0x41000              ; sectors to write

start:  MOV  sp, #0x100000      ; top of the CPU card's RAM
        BSR  __con_init
        CALL main
        BSR  __con_flush
        HALT

; isr: the card's interrupt (nothing else interrupts). Reading the status
; acknowledges it.
isr:    PUSH r1
        MOV  r1, byte [CF_STAT]
        ST   r1, byte [irq_status]
        MOV  r1, [irqs]
        INC  r1
        ST   r1, [irqs]
        POP  r1
        RTI

fatal:  LEA  r1, [s_fatal]
        BSR  puts
        BSR  __con_flush
        HALT

main:   SAVE r8-r11
        LEA  r1, [s_title]
        BSR  puts
        MOV  r1, #NIEN          ; polled until part 7
        ST   r1, byte [CF_CTRL]

        ; ---- 1. the reset signature ----
        BSR  wait_ready
        LEA  r1, [s_reset]
        BSR  puts
        BSR  task_file

        ; ---- 2. 8-bit transfers ----
        MOV  r1, #1
        ST   r1, byte [CF_FEAT]
        MOV  r1, #C_FEAT
        MOV  r2, #0
        MOV  r3, #0
        BSR  command
        BSR  wait_ready
        LEA  r1, [s_feat]
        BSR  puts
        BSR  task_file

        ; ---- 3. IDENTIFY DEVICE ----
        MOV  r1, #C_IDENT
        MOV  r2, #0
        MOV  r3, #1
        BSR  command
        BSR  wait_drq
        MOV  r1, #BUF
        BSR  read_sector
        LEA  r1, [s_ident]
        BSR  puts
        MOV  r1, half [BUF]     ; word 0: the general configuration
        MOV  r2, #4
        BSR  print_hex
        LEA  r1, [s_model]
        MOV  r2, #BUF + 2 * 27  ; words 27-46
        MOV  r3, #20
        BSR  show_string
        LEA  r1, [s_serial]
        MOV  r2, #BUF + 2 * 10  ; words 10-19
        MOV  r3, #10
        BSR  show_string
        LEA  r1, [s_firmware]
        MOV  r2, #BUF + 2 * 23  ; words 23-26
        MOV  r3, #4
        BSR  show_string
        LEA  r1, [s_size]
        BSR  puts
        MOV  r1, half [BUF + 2 * 61]    ; words 60-61: sectors by LBA
        LSL  r1, #16
        OR   r1, half [BUF + 2 * 60]
        BSR  print_u32
        LEA  r1, [s_sectors]
        BSR  puts
        BSR  task_file

        ; ---- 4. reads ----
        LEA  r1, [s_read]
        BSR  puts
        MOV  r1, #C_READ
        MOV  r2, #3
        MOV  r3, #2
        BSR  command
        MOV  r1, #BUF
        MOV  r2, #2
        BSR  read_sectors
        MOV  r1, #BUF
        MOV  r2, #3
        BSR  check
        MOV  r1, #BUF + 512
        MOV  r2, #4
        BSR  check
        MOV  r1, #C_READ
        MOV  r2, #SECTORS - 1
        MOV  r3, #1
        BSR  command
        MOV  r1, #BUF
        MOV  r2, #1
        BSR  read_sectors
        MOV  r1, #BUF
        MOV  r2, #SECTORS - 1
        BSR  check
        BSR  task_file

        ; ---- 5. writes ----
        MOV  r1, #WBUF          ; three sectors of (i / 2) xor i
        MOV  r2, #0
.fill:  MOV  r3, r2
        LSR  r3, #1
        XOR  r3, r2
        ST   r3, byte [r1]+
        INC  r2
        CMP  r2, #3 * 512
        BNE  .fill
        MOV  r1, #WBUF
        LEA  r2, [s_w100]
        BSR  strcpy
        MOV  r1, #WBUF + 512
        LEA  r2, [s_w101]
        BSR  strcpy
        MOV  r1, #WBUF + 1024
        LEA  r2, [s_w102]
        BSR  strcpy
        LEA  r1, [s_write]
        BSR  puts
        MOV  r1, #C_WRITE
        MOV  r2, #100
        MOV  r3, #3
        BSR  command
        MOV  r8, #WBUF
        MOV  r9, #3
.wsec:  BSR  wait_drq
        MOV  r1, r8
        BSR  write_sector
        MOV  r8, r1
        DEC  r9
        BNE  .wsec
        BSR  wait_ready
        BSR  task_file
        MOV  r1, #C_READ        ; read them back
        MOV  r2, #100
        MOV  r3, #3
        BSR  command
        MOV  r1, #BUF
        MOV  r2, #3
        BSR  read_sectors
        LEA  r1, [s_back]
        BSR  puts
        MOV  r1, #BUF
        BSR  puts
        LEA  r1, [s_quote2]
        BSR  puts
        MOV  r1, #BUF
        MOV  r2, #WBUF
        MOV  r3, #3 * 512
        BSR  compare
        BSR  result
        BSR  newline

        ; ---- 6. errors ----
        LEA  r1, [s_verify]
        BSR  puts
        MOV  r1, #C_VERIFY
        MOV  r2, #SECTORS - 8
        MOV  r3, #8
        BSR  command
        BSR  wait_ready
        BSR  task_file
        LEA  r1, [s_vend]
        BSR  puts
        MOV  r1, #C_VERIFY
        MOV  r2, #SECTORS - 4
        MOV  r3, #8
        BSR  command
        BSR  wait_ready
        BSR  task_file
        LEA  r1, [s_rend]
        BSR  puts
        MOV  r1, #C_READ
        MOV  r2, #SECTORS
        MOV  r3, #1
        BSR  command
        BSR  wait_ready
        BSR  task_file
        LEA  r1, [s_nop]
        BSR  puts
        MOV  r1, #C_NOP
        MOV  r2, #0
        MOV  r3, #0
        BSR  command
        BSR  wait_ready
        BSR  task_file

        ; ---- 7. with interrupts ----
        LEA  r1, [s_irq]
        BSR  puts
        MOV  r1, byte [CF_STAT] ; acknowledge what the polled part left
        ST   r0, [irqs]
        ST   r0, byte [CF_CTRL] ; nIEN off: the card interrupts
        MOV  r1, #C_READ        ; two sectors: an interrupt for each
        MOV  r2, #9
        MOV  r3, #2
        BSR  command
        MOV  r1, #1
        BSR  wait_irq
        MOV  r1, #BUF
        BSR  read_sector
        MOV  r1, #2
        BSR  wait_irq
        MOV  r1, #BUF + 512
        BSR  read_sector
        MOV  r1, #BUF
        MOV  r2, #9
        BSR  check
        MOV  r1, #BUF + 512
        MOV  r2, #10
        BSR  check
        MOV  r1, #C_WRITE       ; one sector: no interrupt before the data,
        MOV  r2, #200           ; one when it's written
        MOV  r3, #1
        BSR  command
        BSR  wait_drq
        MOV  r1, #WBUF + 512
        BSR  write_sector
        MOV  r1, #3
        BSR  wait_irq
        MOV  r1, #C_READ        ; and back
        MOV  r2, #200
        MOV  r3, #1
        BSR  command
        MOV  r1, #4
        BSR  wait_irq
        MOV  r1, #BUF
        BSR  read_sector
        LEA  r1, [s_back]
        BSR  puts
        MOV  r1, #BUF
        BSR  puts
        LEA  r1, [s_quote2]
        BSR  puts
        MOV  r1, #BUF
        MOV  r2, #WBUF + 512
        MOV  r3, #512
        BSR  compare
        BSR  result
        BSR  newline
        LEA  r1, [s_irqs]
        BSR  puts
        MOV  r1, [irqs]
        BSR  print_u32
        LEA  r1, [s_last]
        BSR  puts
        MOV  r1, byte [irq_status]
        BSR  hex2
        BSR  newline
        MOV  r1, #NIEN
        ST   r1, byte [CF_CTRL]

        RESTORE r8-r11
        RET

; ---- the card ----

; wait_ready: until the card isn't busy (the alternate status, which leaves
; the interrupt alone). Clobbers r1.
wait_ready:
        MOV  r1, byte [CF_ALT]
        AND  r1, #BSY
        BNE  wait_ready
        RET

; wait_drq: until the card isn't busy, then fatal unless it wants data
; moved. Clobbers r1.
wait_drq:
        BSR  wait_ready
        MOV  r1, byte [CF_ALT]
        AND  r1, #DRQ
        BEQ  fatal
        RET

; command: r1 = a command, r2 = an LBA, r3 = a sector count. Waits until the
; card isn't busy, sets the task file and starts the command.
; Clobbers r1, r2.
command:
        PUSH r1
        BSR  wait_ready
        ST   r3, byte [CF_COUNT]
        ST   r2, byte [CF_LBA0]
        LSR  r2, #8
        ST   r2, byte [CF_LBA1]
        LSR  r2, #8
        ST   r2, byte [CF_LBA2]
        LSR  r2, #8
        AND  r2, #0x0F
        OR   r2, #0xE0          ; LBA, device 0
        ST   r2, byte [CF_HEAD]
        POP  r1
        ST   r1, byte [CF_CMD]
        RET

; read_sector: r1 = a buffer: move one sector from the card.
; -> r1 = the end of the buffer. Clobbers r2, r3.
read_sector:
        MOV  r2, #512
.loop:  MOV  r3, byte [CF_DATA]
        ST   r3, byte [r1]+
        DEC  r2
        BNE  .loop
        RET

; read_sectors: r1 = a buffer, r2 = sectors: polled. Clobbers r1-r5.
read_sectors:
        MOV  r4, r1
        MOV  r5, r2
.loop:  BSR  wait_drq
        MOV  r1, r4
        BSR  read_sector
        MOV  r4, r1
        DEC  r5
        BNE  .loop
        RET

; write_sector: r1 = a buffer: move one sector to the card.
; -> r1 = the end of the buffer. Clobbers r2, r3.
write_sector:
        MOV  r2, #512
.loop:  MOV  r3, byte [r1]+
        ST   r3, byte [CF_DATA]
        DEC  r2
        BNE  .loop
        RET

; wait_irq: r1 = a number of interrupts: sleep until the handler has
; counted that many. Call with interrupts off; returns with them off. The
; test and HALT can't be split by the interrupt: it can't be taken right
; after EI, only once HALT waits.
wait_irq:
.wait:  CMP  r1, [irqs]
        BLS  .done
        EI
        HALT
        DI
        BRA  .wait
.done:  RET

; ---- printing ----

; task_file: print the status (the alternate status), error, sector count
; and address. Clobbers r1-r6.
task_file:
        LEA  r1, [s_status]
        BSR  puts
        MOV  r1, byte [CF_ALT]
        BSR  hex2
        LEA  r1, [s_error]
        BSR  puts
        MOV  r1, byte [CF_ERR]
        BSR  hex2
        LEA  r1, [s_count]
        BSR  puts
        MOV  r1, byte [CF_COUNT]
        BSR  hex2
        LEA  r1, [s_lba]
        BSR  puts
        MOV  r1, byte [CF_HEAD]
        AND  r1, #0x0F
        MOV  r2, #1
        BSR  print_hex
        MOV  r1, byte [CF_LBA2]
        BSR  hex2
        MOV  r1, byte [CF_LBA1]
        BSR  hex2
        MOV  r1, byte [CF_LBA0]
        BSR  hex2
        BRA  newline

hex2:   MOV  r2, #2
        BRA  print_hex

; show_string: r1 = a label, r2 = an ATA string in IDENTIFY's data, r3 =
; its words: print the label and the string, without its trailing spaces.
; Two characters a word, the first in the upper byte. Clobbers r1-r6.
show_string:
        PUSH r2
        PUSH r3
        BSR  puts
        POP  r3
        POP  r1
        LEA  r4, [text]         ; r4 = where the next character goes
.copy:  MOV  r5, byte [r1 + 1]
        ST   r5, byte [r4]+
        MOV  r5, byte [r1]
        ST   r5, byte [r4]+
        ADD  r1, #2
        DEC  r3
        BNE  .copy
        LEA  r5, [text]
.trim:  CMP  r4, r5
        BEQ  .done
        MOV  r6, byte [r4 - 1]
        CMP  r6, #' '
        BNE  .done
        DEC  r4
        BRA  .trim
.done:  ST   r0, byte [r4]
        MOV  r1, r5
        BSR  puts
        LEA  r1, [s_quote]
        BRA  puts

; check: r1 = a sector's data, r2 = its number: print its text and whether
; the rest follows cf_disk()'s pattern. Clobbers r1-r7.
check:  SAVE r8-r9
        MOV  r8, r1
        MOV  r9, r2
        LEA  r1, [s_sector]
        BSR  puts
        MOV  r1, r8
        BSR  puts
        LEA  r1, [s_quote2]
        BSR  puts
        MOV  r1, r8
        BSR  strlen
        INC  r1                 ; r1 = the first byte of the pattern
        MOV  r6, #0             ; r6 = bytes that differ
.loop:  MOV  r2, r9
        ADD  r2, r1
        AND  r2, #0xFF
        CMP  r2, byte [r8 + r1]
        BEQ  .ok
        INC  r6
.ok:    INC  r1
        CMP  r1, #512
        BNE  .loop
        MOV  r1, r6
        BSR  result
        BSR  newline
        RESTORE r8-r9
        RET

; compare: r1, r2 = two buffers, r3 = bytes. -> r1 = bytes that differ
compare:
        MOV  r4, #0
.loop:  MOV  r5, byte [r1]+
        CMP  r5, byte [r2]+
        BEQ  .same
        INC  r4
.same:  DEC  r3
        BNE  .loop
        MOV  r1, r4
        RET

; result: r1 = how many bytes differ: print "the pattern" or the number.
; Clobbers r1-r6.
result: TST  r1, r1
        BNE  .bad
        LEA  r1, [s_ok]
        BRA  puts
.bad:   BSR  print_u32
        LEA  r1, [s_differ]
        BRA  puts

        .align 4
irqs:       .word 0
irq_status: .byte 0
        .align 2
text:       .space 48
s_title:    .asciz "CF card\n"
s_reset:    .asciz "after reset:     "
s_feat:     .asciz "8-bit transfers: "
s_ident:    .asciz "identify: configuration "
s_model:    .asciz ", model \""
s_serial:   .asciz ", serial \""
s_firmware: .asciz ", firmware \""
s_size:     .asciz ", "
s_sectors:  .asciz " sectors\n          "
s_read:     .asciz "read:\n"
s_sector:   .asciz "  \""
s_quote:    .asciz "\""
s_quote2:   .asciz "\", "
s_ok:       .asciz "ok"
s_differ:   .asciz " bytes differ"
s_write:    .asciz "write 3 sectors: "
s_back:     .asciz "  read back \""
s_verify:   .asciz "verify:          "
s_vend:     .asciz "verify past end: "
s_rend:     .asciz "read past end:   "
s_nop:      .asciz "NOP:             "
s_irq:      .asciz "with interrupts:\n"
s_irqs:     .asciz "  interrupts: "
s_last:     .asciz ", last status "
s_status:   .asciz "status "
s_error:    .asciz " error "
s_count:    .asciz " count "
s_lba:      .asciz " lba "
s_w100:     .asciz "written by cfcard, 1"
s_w101:     .asciz "written by cfcard, 2"
s_w102:     .asciz "written by cfcard, 3"
s_fatal:    .asciz "TRAP\n"
        .align 2

        .include "lib/uart.s"
        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/string.s"
