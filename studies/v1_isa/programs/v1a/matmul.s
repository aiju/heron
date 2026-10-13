; matmul: C = A * B for 8 x 8 matrices of random numbers -2048..2047
; (xorshift16 seeded with 2024: A's elements in row order, then B's), with
; 32-bit sums. Prints row 3 of C, the trace, and a checksum: the sum of all
; of C mod 2^32 and Fletcher-16 sums over its words' 16-bit halves, low half
; first.
;
; Every number is a word. B is stored transposed as it is generated, so
; C[i][j] is the dot product of row i of A and row j of B transposed. With
; the k loop unrolled, all sixteen loads are one-parcel [reg + 4k] forms
; (offsets 0-28) and no pointer moves inside the dot product.

        .include "lib/start.s"

N   = 8
ROW = 4 * N                     ; bytes per matrix row

main:   SAVE r8-r11
        LI   r1, #2024
        BSR  srand
        LEA  r8, mat_a          ; A in row order
        LEA  r9, bt             ; (A ends where bt starts)
.filla: BSR  rand
        LSR  r1, #4             ; 12 random bits,
        SUB  r1, #2048          ; centred on 0
        ST   r1, [r8]
        ADDI r8, 4
        CMP  r8, r9
        BNE  .filla
.fillb: MOV  r10, r9            ; B's row i becomes column i of bt:
        MVI  r11, N             ; r10 = bt[j][i], going down the column
.fbcol: BSR  rand
        LSR  r1, #4
        SUB  r1, #2048
        ST   r1, [r10]
        ADDI r10, ROW
        ADDI r11, -1
        BNE  .fbcol
        ADDI r9, 4
        CMP  r9, #bt + ROW
        BNE  .fillb

        ; ---- multiply: no calls in here, so scratch registers only ----
        LEA  r4, mat_a          ; r4 = row i of A
        LEA  r7, mat_c          ; r7 = C[i][j], filled in order
.row:   LEA  r5, bt             ; r5 = row j of bt = column j of B
.col:   LD   r3, [r4]           ; r3 = sum, starting with k = 0
        LD   r2, [r5]
        MULS r3, r2
        LD   r1, [r4 + 4]       ; k = 1
        LD   r2, [r5 + 4]
        MULS r1, r2
        ADD  r3, r1
        LD   r1, [r4 + 8]       ; k = 2
        LD   r2, [r5 + 8]
        MULS r1, r2
        ADD  r3, r1
        LD   r1, [r4 + 12]      ; k = 3
        LD   r2, [r5 + 12]
        MULS r1, r2
        ADD  r3, r1
        LD   r1, [r4 + 16]      ; k = 4
        LD   r2, [r5 + 16]
        MULS r1, r2
        ADD  r3, r1
        LD   r1, [r4 + 20]      ; k = 5
        LD   r2, [r5 + 20]
        MULS r1, r2
        ADD  r3, r1
        LD   r1, [r4 + 24]      ; k = 6
        LD   r2, [r5 + 24]
        MULS r1, r2
        ADD  r3, r1
        LD   r1, [r4 + 28]      ; k = 7
        LD   r2, [r5 + 28]
        MULS r1, r2
        ADD  r3, r1
        ST   r3, [r7]
        ADDI r7, 4
        ADDI r5, ROW
        CMP  r5, #bt + ROW * N
        BNE  .col
        ADDI r4, ROW
        CMP  r4, #mat_a + ROW * N
        BNE  .row

        ; ---- report ----
        LEA  r1, s_row
        BSR  puts
        LEA  r8, mat_c + 3 * ROW
        MVI  r9, N
.prow:  BSR  space
        LD   r1, [r8]
        BSR  print_s32
        ADDI r8, 4
        ADDI r9, -1
        BNE  .prow
        BSR  newline

        LEA  r1, s_trace
        BSR  puts
        LEA  r2, mat_c
        MVI  r1, 0
        MVI  r3, N
.trace: LD   r4, [r2]           ; C[i][i]: ROW + 4 bytes apart
        ADD  r1, r4
        ADDI r2, ROW + 4
        ADDI r3, -1
        BNE  .trace
        BSR  print_s32
        BSR  newline

        ; The Fletcher sums are kept in 32 bits and only their low halves
        ; printed: (a + b) mod 2^16 is the low half of the 32-bit sum, so
        ; masking at every step would change nothing.
        LEA  r1, s_sum
        BSR  puts
        LEA  r7, mat_c
        LEA  r6, [r7 + ROW * N] ; r6 = end of C
        MVI  r9, 0              ; r9 = sum of the words
        MVI  r10, 0             ; r10 = s1
        MVI  r11, 0             ; r11 = s2
.sum:   LD   r1, [r7]
        ADD  r9, r1
        ZXH  r2, r1             ; low half
        ADD  r10, r2
        ADD  r11, r10
        LSR  r1, #16            ; high half
        ADD  r10, r1
        ADD  r11, r10
        ADDI r7, 4
        CMP  r7, r6
        BNE  .sum
        MOV  r1, r9
        MVI  r2, 8
        BSR  print_hex
        BSR  space
        MOV  r1, r10
        MVI  r2, 4
        BSR  print_hex
        BSR  space
        MOV  r1, r11
        MVI  r2, 4
        BSR  print_hex
        BSR  newline
        RESTORE r8-r11
        RET

s_row:   .asciz "row 3:"
s_trace: .asciz "trace: "
s_sum:   .asciz "checksum: "
        .align 2

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/rand.s"

        .align 4
mat_a:  .space ROW * N
bt:     .space ROW * N          ; B transposed: bt[j][k] = B[k][j]
mat_c:  .space ROW * N
