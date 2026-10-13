; matmul: C = A * B for 8 x 8 matrices of signed 16-bit numbers (random,
; -2048..2047), with 32-bit sums. Prints one row of C, the trace and a
; checksum.

        .include "lib/start.s"

N = 8

main:   PUSH r8
        PUSH r9
        PUSH r10
        PUSH r11
        PUSH r12
        PUSH r13
        PUSH r14

        LI   r1, #2024
        CALL srand
        LI   r8, #mat_a         ; fill A, then B (they are adjacent)
        LI   r9, #2 * N * N
.fill:  CALL rand
        SHR  r1                 ; 12 random bits...
        SHR  r1
        SHR  r1
        SHR  r1
        ADD  r1, #-2048         ; ...centred on 0
        ST   r1, [r8]
        ADDI r8, 2
        DEC  r9
        BNE  .fill

        ; ---- multiply ----
        LI   r8, #mat_a         ; r8 = row i of A
        LI   r13, #mat_c        ; r13 = C[i][j]
        MVI  r14, N             ; rows left
.row:   LI   r11, #mat_b        ; r11 = column j of B
        MVI  r12, N             ; columns left
.col:   MVI  r9, 0              ; r10:r9 = sum
        MVI  r10, 0
        ; The k loop is unrolled: the offsets into the row of A (2k) and
        ; down the column of B (16k) are constants, so there is no counter
        ; and no pointer stepping; offsets above 30 just use the long form.
        LD   r1, [r8]
        LD   r2, [r11]
        CALL smul16
        ADD  r9, r1
        ADC  r10, r2
        LD   r1, [r8 + 2]
        LD   r2, [r11 + 2 * N]
        CALL smul16
        ADD  r9, r1
        ADC  r10, r2
        LD   r1, [r8 + 4]
        LD   r2, [r11 + 4 * N]
        CALL smul16
        ADD  r9, r1
        ADC  r10, r2
        LD   r1, [r8 + 6]
        LD   r2, [r11 + 6 * N]
        CALL smul16
        ADD  r9, r1
        ADC  r10, r2
        LD   r1, [r8 + 8]
        LD   r2, [r11 + 8 * N]
        CALL smul16
        ADD  r9, r1
        ADC  r10, r2
        LD   r1, [r8 + 10]
        LD   r2, [r11 + 10 * N]
        CALL smul16
        ADD  r9, r1
        ADC  r10, r2
        LD   r1, [r8 + 12]
        LD   r2, [r11 + 12 * N]
        CALL smul16
        ADD  r9, r1
        ADC  r10, r2
        LD   r1, [r8 + 14]
        LD   r2, [r11 + 14 * N]
        CALL smul16
        ADD  r9, r1
        ADC  r10, r2
        ST   r9, [r13]
        ST   r10, [r13 + 2]
        ADDI r13, 4
        ADDI r11, 2             ; next column
        DEC  r12
        BNE  .col
        ADDI r8, 2 * N          ; next row
        DEC  r14
        BNE  .row

        ; ---- report ----
        LI   r1, #s_row
        CALL puts
        LI   r8, #mat_c + 3 * 4 * N
        MVI  r9, N
.prow:  CALL space
        LD   r1, [r8]
        LD   r2, [r8 + 2]
        CALL print_s32
        ADDI r8, 4
        DEC  r9
        BNE  .prow
        CALL newline

        LI   r1, #s_trace       ; sum of C[i][i]: stride 4 * (N + 1) bytes
        CALL puts
        LI   r8, #mat_c
        MVI  r9, N
        MVI  r10, 0
        MVI  r11, 0
.trace: LD   r1, [r8]
        LD   r2, [r8 + 2]
        ADD  r10, r1
        ADC  r11, r2
        ADDI r8, 4 * (N + 1)
        DEC  r9
        BNE  .trace
        MOV  r1, r10
        MOV  r2, r11
        CALL print_s32
        CALL newline

        LI   r1, #s_sum         ; checksum: the sum of all of C (mod 2^32),
        CALL puts               ; and Fletcher sums over its 128 words
        LI   r8, #mat_c
        MVI  r9, N * N
        MVI  r10, 0             ; r11:r10 = sum
        MVI  r11, 0
        MVI  r12, 0             ; r12 = s1, r13 = s2
        MVI  r13, 0
.sum:   LD   r1, [r8]
        LD   r2, [r8 + 2]
        ADD  r10, r1            ; the ADC must come right after the ADD:
        ADC  r11, r2            ; every add, ADDI and DEC rewrites C
        ADD  r12, r1
        ADD  r13, r12
        ADD  r12, r2
        ADD  r13, r12
        ADDI r8, 4
        DEC  r9
        BNE  .sum
        MOV  r1, r10
        MOV  r2, r11
        CALL print_hex32
        CALL space
        MOV  r1, r12
        CALL print_hex16
        CALL space
        MOV  r1, r13
        CALL print_hex16
        CALL newline

        POP  r14
        POP  r13
        POP  r12
        POP  r11
        POP  r10
        POP  r9
        POP  r8
        RET

s_row:   .asciz "row 3:"
s_trace: .asciz "trace: "
s_sum:   .asciz "checksum: "

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/mul.s"
        .include "lib/rand.s"

        .align 2
mat_a:  .space 2 * N * N
mat_b:  .space 2 * N * N
mat_c:  .space 4 * N * N
