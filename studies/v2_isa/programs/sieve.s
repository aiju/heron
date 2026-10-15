; sieve: Sieve of Eratosthenes over a byte array, primes below 8192.
; Prints how many there are and the last ten.
;
; flags[i] = 1 means "i may be prime". Each prime i crosses off i*i, i*i + i,
; ... (smaller multiples were already crossed off by smaller primes), for
; i*i < N. The flags are 0 or 1, so counting is just adding them up.

        .include "lib/start.s"

N = 8192

main:   SAVE r8-r11

        MOV  r1, #flags
        MOV  r2, #1
        MOV  r3, #N
        BSR  memset
        CLR  half [flags]       ; 0 and 1 are not primes: one store clears both

        ; ---- sieve ----
        MOV  r8, #2             ; r8 = i
        MOV  r9, #4             ; r9 = i * i, kept up to date by adding 2i + 1
        MOV  r11, #flags + N    ; r11 = end of the array
.outer: MOVS r1, byte [flags + r8]
        BEQ  .next
        LEA  r10, [flags + r9]  ; r10 = &flags[i * i]
.cross: CLR  byte [r10]
        ADD  r10, r8
        CMP  r10, r11
        BLO  .cross
.next:  ADD  r9, r8
        ADD  r9, r8
        INC  r9
        INC  r8
        CMP  r9, #N
        BLO  .outer

        ; ---- count: a byte add straight from memory, four per iteration ----
        MOV  r9, #0
        MOV  r10, #flags
.count: ADD  r9, byte [r10]+
        ADD  r9, byte [r10]+
        ADD  r9, byte [r10]+
        ADD  r9, byte [r10]+
        CMP  r10, r11
        BLO  .count
        LEA  r1, [s_count]
        BSR  puts
        MOV  r1, r9
        BSR  print_u32
        BSR  newline

        ; ---- the last ten: scanning down, push each prime found, so the
        ; smallest of the ten ends up on top of the stack ----
        MOV  r10, #N
        MOV  r9, #10
.scan:  DEC  r10
        MOVS r1, byte [flags + r10]
        BEQ  .scan
        PUSH r10
        DBNZ r9, .scan
        LEA  r1, [s_last]
        BSR  puts
        MOV  r9, #10
.print: BSR  space
        POP  r1
        BSR  print_u32
        DBNZ r9, .print
        BSR  newline

        RESTORE r8-r11
        RET

s_count: .asciz "primes below 8192: "
s_last:  .asciz "last ten:"

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/string.s"

        .align 4
flags:  .space N
