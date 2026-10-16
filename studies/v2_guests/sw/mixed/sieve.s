; A user process in draft 2 code under the mixed kernel: the suite's
; sieve (primes below 8192, the count and the last ten), printed to the
; process's console page at VA 0xFFF000. It uses no multiply or divide and
; none of the cells where the tools in this tree and the v2_hw study's
; microcode still differ, so it runs on that microcode as it is. The
; flags are past the image: the kernel maps their pages as they are
; touched. SWI #0 ends it.

N       = 8192
CONSOLE = 0xFFF000

        .org 0
start:  MOV  sp, #0x100000
        MOV  r9, #CONSOLE
        MOV  r10, #flags
        CLR  r11                ; the count
        CLR  r12                ; where the next prime goes in last
        MOV  r1, #2             ; i
.loop:  MOV  r3, r10
        ADD  r3, r1
        MOVS r4, byte [r3]
        BNE  .next              ; composite
        INC  r11
        MOV  r3, #last
        ADD  r3, r12
        MOV  [r3], r1
        ADD  r12, #4
        CMP  r12, #40
        BNE  .mark
        CLR  r12
.mark:  MOV  r2, r1             ; j = 2i, 3i, ...: flags[j] = 1
        MOV  r4, #1
.m:     ADD  r2, r1
        CMP  r2, #N
        BHS  .next
        MOV  r3, r10
        ADD  r3, r2
        MOV  byte [r3], r4
        BRA  .m
.next:  INC  r1
        CMP  r1, #N
        BLO  .loop

        MOV  r1, #s_count
        BSR  puts
        MOV  r1, r11
        BSR  print_u32
        MOV  r1, #s_last
        BSR  puts
        MOV  r13, #10           ; the last ten, oldest first: from r12 on
.p:     MOV  r1, #' '
        MOV  byte [r9], r1
        MOV  r3, #last
        ADD  r3, r12
        MOV  r1, [r3]
        BSR  print_u32
        ADD  r12, #4
        CMP  r12, #40
        BNE  .pn
        CLR  r12
.pn:    DBNZ r13, .p
        MOV  r1, #10
        MOV  byte [r9], r1
        SWI  #0

; puts: r1 = a NUL-terminated string. Clobbers r1, r2
puts:   MOVS r2, byte [r1]+
        BEQ  .done
        MOV  byte [r9], r2
        BRA  puts
.done:  RET

; print_u32: r1 unsigned, in decimal, by subtracting powers of ten.
; Clobbers r1-r5
print_u32:
        MOV  r4, #pow10
        CLR  r5
.next:  MOV  r2, [r4]+
        CLR  r3
.sub:   CMP  r1, r2
        BLO  .digit
        SUB  r1, r2
        INC  r3
        BRA  .sub
.digit: OR   r5, r3
        CMP  r2, #1
        BEQ  .out
        TST  r5, r5
        BEQ  .next
.out:   ADD  r3, #'0'
        MOV  byte [r9], r3
        CMP  r2, #1
        BNE  .next
        RET

        .align 4
pow10:  .word 1000000000, 100000000, 10000000, 1000000, 100000, 10000, 1000, 100, 10, 1
last:   .space 40
s_count: .asciz "primes below 8192: "
s_last: .asciz "\nlast ten:"
        .align 4
flags:
