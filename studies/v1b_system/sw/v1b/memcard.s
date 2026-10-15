; memcard: the memory card in slot 1 (2 MB at 0x10000000) and what the bus
; does with the other slots.
;
;  1. every slot's ID: the memory card's is at A27, the I/O card's in bits
;     8-15 of any read; an empty slot is a bus error, which traps through
;     the address error vector and is caught here
;  2. words, halves and bytes, each written and read back in every width,
;     and single bytes and halves written into words, so each byte lane is
;     checked both ways
;  3. the address lines: a word at every power of two, and the card's
;     repeat at 2 MB
;  4. misaligned accesses to the card (address errors before the bus) and
;     a write to an empty slot (a bus error)
;  5. memcpy from the CPU card's RAM to the memory card and back
;  6. a sieve of Eratosthenes with its table on the memory card
;
; Nothing printed depends on how long anything takes.

        .org 0x00
        JMP  start              ; reset
        .org 0x04
        RTI                     ; IRQ: none are enabled
        .org 0x08
        JMP  fatal              ; illegal instruction
        .org 0x0C
        JMP  fatal              ; SWI
        .org 0x10
        JMP  fatal              ; divide error
        .org 0x14
        JMP  addr_trap          ; address error, and bus error
        .org 0x18

MEM      = 0x10000000           ; the memory card
ID_OFS   = 0x080000DC           ; A27; on the I/O card, the UART's scratch
                                ; register, which has no side effects
LOCAL    = 0x40000              ; a buffer in the CPU card's RAM
MULT     = 1664525              ; the test patterns' linear congruential
INCR     = 1013904223           ; sequence
WORDS    = 64                   ; words in each width test
SIEVE    = 10000

start:  MOV  sp, #0x100000      ; top of the CPU card's RAM
        BSR  __con_init
        CALL main
        BSR  __con_flush
        HALT

; addr_trap: an address error or a bus error. The saved PC is the faulting
; instruction's. With `resume` set, a test expects the trap: count it and
; carry on at `resume` (cleared again). Otherwise it's fatal.
addr_trap:
        PUSH r1
        MOV  r1, [resume]
        BEQ  .fatal
        ST   r1, [sp + 8]       ; the saved PC, above r1 and the flags
        ST   r0, [resume]
        MOV  r1, [traps]
        INC  r1
        ST   r1, [traps]
        POP  r1
        RTI
.fatal: POP  r1
fatal:  LEA  r1, [s_fatal]
        BSR  puts
        BSR  __con_flush
        HALT

main:   SAVE r8-r11
        LEA  r1, [s_title]
        BSR  puts

        ; ---- 1. the slots ----
        MOV  r8, #1
.slot:  LEA  r1, [s_slot]
        BSR  puts
        MOV  r1, r8
        BSR  print_u32
        LEA  r1, [s_colon]
        BSR  puts
        MOV  r1, r8
        LSL  r1, #28
        OR   r1, #ID_OFS
        BSR  probe
        TST  r1, r1
        BMI  .empty
        MOV  r2, #4
        BSR  print_hex
        BRA  .next
.empty: LEA  r1, [s_empty]
        BSR  puts
.next:  BSR  newline
        INC  r8
        CMP  r8, #16
        BNE  .slot
        LEA  r1, [s_berr]
        BSR  puts
        MOV  r1, [traps]
        BSR  print_u32
        BSR  newline

        ; ---- 2. widths ----
        MOV  r8, #0             ; r8 = 4 x the writer
.wr:    LEA  r1, [s_write]
        BSR  puts
        MOV  r1, [names + r8]
        BSR  puts
        LEA  r1, [s_read]
        BSR  puts
        MOV  r9, #0             ; r9 = 4 x the reader
.rd:    MOV  r1, [names + r9]
        BSR  puts
        MOV  r1, #' '
        BSR  putc
        MOV  r1, #MEM + 0x1000
        MOV  r2, #WORDS
        MOV  r3, r8
        LSL  r3, #4
        ADD  r3, r9             ; a seed for each combination
        CALL [writers + r8]
        MOV  r1, #MEM + 0x1000
        MOV  r2, #WORDS
        MOV  r3, r8
        LSL  r3, #4
        ADD  r3, r9
        CALL [readers + r9]
        BSR  result
        ADD  r9, #4
        CMP  r9, #12
        BEQ  .rdone
        LEA  r1, [s_comma]
        BSR  puts
        BRA  .rd
.rdone: BSR  newline
        ADD  r8, #4
        CMP  r8, #12
        BNE  .wr

        ; single bytes into words: word i is 5A5A5A5A with byte i mod 4 = i
        MOV  r1, #MEM + 0x2000
        MOV  r2, #WORDS
        MOV  r3, #0x5A5A5A5A
.bfill: ST   r3, [r1]+
        DEC  r2
        BNE  .bfill
        MOV  r1, #MEM + 0x2000  ; r1 = word i
        MOV  r2, #0             ; r2 = i
.bpoke: MOV  r3, r2
        AND  r3, #3
        ST   r2, byte [r1 + r3]
        ADD  r1, #4
        INC  r2
        CMP  r2, #WORDS
        BNE  .bpoke
        MOV  r1, #MEM + 0x2000
        MOV  r2, #0
        MOV  r6, #0             ; r6 = words that differ
.bchk:  MOV  r3, r2
        AND  r3, #3
        LSL  r3, #3             ; the byte's shift
        MOV  r4, #0xFF
        LSL  r4, r3
        MOV  r5, r2
        LSL  r5, r3
        MOV  r7, #0x5A5A5A5A
        BIC  r7, r4
        OR   r7, r5
        CMP  r7, [r1]+
        BEQ  .bok
        INC  r6
.bok:   INC  r2
        CMP  r2, #WORDS
        BNE  .bchk
        LEA  r1, [s_sbytes]
        BSR  puts
        MOV  r1, r6
        BSR  result
        BSR  newline

        ; single halves into words: word i is A5A5A5A5 with half i mod 2 = i
        MOV  r1, #MEM + 0x3000
        MOV  r2, #WORDS
        MOV  r3, #0xA5A5A5A5
.hfill: ST   r3, [r1]+
        DEC  r2
        BNE  .hfill
        MOV  r1, #MEM + 0x3000
        MOV  r2, #0
.hpoke: MOV  r3, r2
        AND  r3, #1
        ADD  r3, r3             ; 2 x (i mod 2)
        ST   r2, half [r1 + r3]
        ADD  r1, #4
        INC  r2
        CMP  r2, #WORDS
        BNE  .hpoke
        MOV  r1, #MEM + 0x3000
        MOV  r2, #0
        MOV  r6, #0
.hchk:  MOV  r3, r2
        AND  r3, #1
        LSL  r3, #4             ; the half's shift
        MOV  r4, #0xFFFF
        LSL  r4, r3
        MOV  r5, r2
        LSL  r5, r3
        MOV  r7, #0xA5A5A5A5
        BIC  r7, r4
        OR   r7, r5
        CMP  r7, [r1]+
        BEQ  .hok
        INC  r6
.hok:   INC  r2
        CMP  r2, #WORDS
        BNE  .hchk
        LEA  r1, [s_shalves]
        BSR  puts
        MOV  r1, r6
        BSR  result
        BSR  newline

        ; ---- 3. the address lines ----
        MOV  r8, #MEM
        MOV  r1, #0x600DF00D
        ST   r1, [r8]
        MOV  r2, #2             ; r2 = k: a word at MEM + 2^k
.afill: MOV  r3, #1
        LSL  r3, r2
        MOV  r4, r2
        ADD  r4, #0x100
        ST   r4, [r8 + r3]
        INC  r2
        CMP  r2, #21
        BNE  .afill
        MOV  r6, #0
        CMP  r1, [r8]
        BEQ  .a0
        INC  r6
.a0:    MOV  r2, #2
.achk:  MOV  r3, #1
        LSL  r3, r2
        MOV  r4, r2
        ADD  r4, #0x100
        CMP  r4, [r8 + r3]
        BEQ  .aok
        INC  r6
.aok:   INC  r2
        CMP  r2, #21
        BNE  .achk
        LEA  r1, [s_addr]
        BSR  puts
        MOV  r1, r6
        BSR  result
        LEA  r1, [s_repeat]
        BSR  puts
        MOV  r1, [MEM + 0x200000]
        MOV  r2, #8
        BSR  print_hex
        BSR  newline

        ; ---- 4. traps ----
        ST   r0, [traps]
        LEA  r1, [.t1]
        ST   r1, [resume]
        MOV  r1, #MEM + 2
        MOV  r2, [r1]           ; a misaligned word: an address error
.t1:    LEA  r1, [.t2]
        ST   r1, [resume]
        MOV  r1, #MEM + 1
        ST   r2, half [r1]      ; a misaligned half
.t2:    LEA  r1, [.t3]
        ST   r1, [resume]
        MOV  r1, #0x50000000
        ST   r2, [r1]           ; a word to slot 5, which is empty
.t3:    ST   r0, [resume]
        LEA  r1, [s_traps]
        BSR  puts
        MOV  r1, [traps]
        BSR  print_u32
        BSR  newline

        ; ---- 5. memcpy both ways ----
        MOV  r1, #LOCAL         ; 4 KB of the sequence in local RAM
        MOV  r2, #1024
        MOV  r3, #77
        BSR  fill_words
        MOV  r1, #MEM + 0x10002 ; to the card, at an odd half: byte copies
        MOV  r2, #LOCAL + 2
        MOV  r3, #4000
        BSR  memcpy
        MOV  r1, #MEM + 0x20000 ; and aligned: word copies
        MOV  r2, #LOCAL
        MOV  r3, #4096
        BSR  memcpy
        MOV  r1, #LOCAL + 0x2000
        MOV  r2, #MEM + 0x20000 ; back from the card
        MOV  r3, #4096
        BSR  memcpy
        MOV  r1, #LOCAL + 0x2000
        MOV  r2, #1024
        MOV  r3, #77
        BSR  check_words
        MOV  r8, r1
        MOV  r1, #MEM + 0x10002
        MOV  r2, #LOCAL + 2
        MOV  r3, #4000
        BSR  compare
        ADD  r8, r1
        LEA  r1, [s_memcpy]
        BSR  puts
        MOV  r1, r8
        BSR  result
        BSR  newline

        ; ---- 6. a sieve on the card ----
        MOV  r8, #MEM + 0x100000        ; r8 = the table: a byte per number
        MOV  r1, r8
        MOV  r2, #0
        MOV  r3, #SIEVE
        BSR  memset
        MOV  r10, #1
        MOV  r9, #2             ; r9 = p
.p:     MOV  r1, r9
        MULU r1, r9             ; p * p
        CMP  r1, #SIEVE
        BHS  .count
        MOV  r2, byte [r8 + r9]
        BNE  .np                ; not a prime
.mark:  ST   r10, byte [r8 + r1]
        ADD  r1, r9
        CMP  r1, #SIEVE
        BLO  .mark
.np:    INC  r9
        BRA  .p
.count: MOV  r1, #2
        MOV  r2, #0             ; primes
        MOV  r3, #0             ; their sum
.c:     MOV  r4, byte [r8 + r1]
        BNE  .cn
        INC  r2
        ADD  r3, r1
.cn:    INC  r1
        CMP  r1, #SIEVE
        BNE  .c
        MOV  r9, r3
        MOV  r8, r2
        LEA  r1, [s_sieve]
        BSR  puts
        MOV  r1, r8
        BSR  print_u32
        LEA  r1, [s_sum]
        BSR  puts
        MOV  r1, r9
        BSR  print_u32
        BSR  newline

        RESTORE r8-r11
        RET

; probe: r1 = an address: read the half there. -> r1 = the half, or -1 if
; the read was a bus error.
probe:  LEA  r2, [.fail]
        ST   r2, [resume]
        MOV  r1, half [r1]
        ST   r0, [resume]
        RET
.fail:  MOV  r1, #-1
        RET

; result: r1 = how many things differ: print "ok", or the number.
; Clobbers r1-r6.
result: TST  r1, r1
        BNE  .bad
        LEA  r1, [s_ok]
        BRA  puts
.bad:   BSR  print_u32
        LEA  r1, [s_differ]
        BRA  puts

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

; The width tests: r1 = address, r2 = words, r3 = the sequence's seed. The
; writers store the sequence a word, a half or a byte at a time; the
; readers read it back the same way and return r1 = words that differ.
; Clobbers r1-r6.
fill_words:
        MOV  r4, #MULT
.loop:  MULU r3, r4
        ADD  r3, #INCR
        ST   r3, [r1]+
        DEC  r2
        BNE  .loop
        RET

fill_halves:                    ; the upper half first
        MOV  r4, #MULT
.loop:  MULU r3, r4
        ADD  r3, #INCR
        MOV  r5, r3
        LSR  r5, #16
        ST   r5, half [r1 + 2]
        ST   r3, half [r1]
        ADD  r1, #4
        DEC  r2
        BNE  .loop
        RET

fill_bytes:
        MOV  r4, #MULT
.loop:  MULU r3, r4
        ADD  r3, #INCR
        MOV  r5, r3
        ST   r5, byte [r1]+
        LSR  r5, #8
        ST   r5, byte [r1]+
        LSR  r5, #8
        ST   r5, byte [r1]+
        LSR  r5, #8
        ST   r5, byte [r1]+
        DEC  r2
        BNE  .loop
        RET

check_words:
        MOV  r4, #MULT
        MOV  r6, #0
.loop:  MULU r3, r4
        ADD  r3, #INCR
        CMP  r3, [r1]+
        BEQ  .ok
        INC  r6
.ok:    DEC  r2
        BNE  .loop
        MOV  r1, r6
        RET

check_halves:
        MOV  r4, #MULT
        MOV  r6, #0
.loop:  MULU r3, r4
        ADD  r3, #INCR
        MOV  r5, half [r1 + 2]
        LSL  r5, #16
        OR   r5, half [r1]
        ADD  r1, #4
        CMP  r5, r3
        BEQ  .ok
        INC  r6
.ok:    DEC  r2
        BNE  .loop
        MOV  r1, r6
        RET

check_bytes:                    ; the highest byte first
        MOV  r4, #MULT
        MOV  r6, #0
.loop:  MULU r3, r4
        ADD  r3, #INCR
        MOV  r5, byte [r1 + 3]
        LSL  r5, #8
        OR   r5, byte [r1 + 2]
        LSL  r5, #8
        OR   r5, byte [r1 + 1]
        LSL  r5, #8
        OR   r5, byte [r1]
        ADD  r1, #4
        CMP  r5, r3
        BEQ  .ok
        INC  r6
.ok:    DEC  r2
        BNE  .loop
        MOV  r1, r6
        RET

        .align 4
writers:  .word fill_words, fill_halves, fill_bytes
readers:  .word check_words, check_halves, check_bytes
names:    .word s_words, s_halves, s_bytes
resume:   .word 0
traps:    .word 0
s_title:  .asciz "memory card and slots\n"
s_slot:   .asciz "slot "
s_colon:  .asciz ": "
s_empty:  .asciz "empty"
s_berr:   .asciz "bus errors: "
s_write:  .asciz "written as "
s_read:   .asciz ", read as "
s_comma:  .asciz ", "
s_words:  .asciz "words"
s_halves: .asciz "halves"
s_bytes:  .asciz "bytes"
s_sbytes: .asciz "bytes into words "
s_shalves: .asciz "halves into words "
s_ok:     .asciz "ok"
s_differ: .asciz " differ"
s_addr:   .asciz "address lines "
s_repeat: .asciz ", at 2 MB "
s_traps:  .asciz "misaligned and empty-slot traps: "
s_memcpy: .asciz "memcpy both ways "
s_sieve:  .asciz "primes below 10000: "
s_sum:    .asciz ", sum "
s_fatal:  .asciz "TRAP\n"
        .align 2

        .include "lib/uart.s"
        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/string.s"
