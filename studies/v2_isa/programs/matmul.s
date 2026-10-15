; matmul: C = A * B for 8 x 8 matrices of random numbers -2048..2047
; (xorshift16 seeded with 2024: A's elements in row order, then B's), with
; 32-bit sums. Prints row 3 of C, the trace, and a checksum: the sum of all
; of C mod 2^32 and Fletcher-16 sums over its words' 16-bit halves, low half
; first.
;
; Every number is a word. B is stored transposed as it is generated, so
; C[i][j] is the dot product of two consecutive runs of words (row i of A,
; row j of B transposed), each walked with an auto-increment operand. The
; k loop is unrolled, each step a MULA: the sum builds up in HI:LO, 64 bits,
; and its low word is C[i][j] mod 2^32.

        .include "lib/start.s"

N   = 8
ROW = 4 * N                     ; bytes per matrix row

main:   SAVE r8-r11
        MOV  r1, #2024
        BSR  srand
        LEA  r8, [mat_a]        ; A in row order
.filla: BSR  rand
        LSR  r1, #4             ; 12 random bits,
        SUB  r1, #2048          ; centred on 0
        MOV  [r8]+, r1
        CMP  r8, #mat_a + ROW * N
        BNE  .filla
        LEA  r8, [bt]           ; B's row i becomes column i of bt
.fillb: MOV  r9, r8             ; r9 = bt[j][i], going down the column
        MOV  r10, #N
.fbcol: BSR  rand
        LSR  r1, #4
        SUB  r1, #2048
        MOV  [r9], r1
        ADD  r9, #ROW
        DBNZ r10, .fbcol
        ADD  r8, #4
        CMP  r8, #bt + ROW
        BNE  .fillb

        ; ---- multiply: no calls in here, so scratch registers only ----
        CLR  r0
        LEA  r4, [mat_a]        ; r4 = row i of A
        LEA  r7, [mat_c]        ; r7 = C[i][j], filled in order
.row:   LEA  r5, [bt]           ; r5 = row j of bt = column j of B
.col:   MOV  r6, r4             ; r6 walks along row i of A
        MTHI r0                 ; HI:LO = sum = 0
        MTLO r0
        MOV  r1, [r6]+          ; k = 0
        MOV  r2, [r5]+
        MULA r1, r2             ; sum += A[i][k] * B[k][j]
        MOV  r1, [r6]+          ; k = 1
        MOV  r2, [r5]+
        MULA r1, r2
        MOV  r1, [r6]+          ; k = 2
        MOV  r2, [r5]+
        MULA r1, r2
        MOV  r1, [r6]+          ; k = 3
        MOV  r2, [r5]+
        MULA r1, r2
        MOV  r1, [r6]+          ; k = 4
        MOV  r2, [r5]+
        MULA r1, r2
        MOV  r1, [r6]+          ; k = 5
        MOV  r2, [r5]+
        MULA r1, r2
        MOV  r1, [r6]+          ; k = 6
        MOV  r2, [r5]+
        MULA r1, r2
        MOV  r1, [r6]+          ; k = 7
        MOV  r2, [r5]+
        MULA r1, r2
        MFLO r3                 ; the sum's low word
        MOV  [r7]+, r3
        CMP  r5, #bt + ROW * N  ; r5 has walked through all of bt: row done
        BNE  .col
        MOV  r4, r6             ; r6 has walked on to row i + 1
        CMP  r4, #mat_a + ROW * N
        BNE  .row

        ; ---- report ----
        LEA  r1, [s_row]
        BSR  puts
        LEA  r8, [mat_c + 3 * ROW]
.prow:  BSR  space
        MOV  r1, [r8]+
        BSR  print_s32
        CMP  r8, #mat_c + 4 * ROW
        BNE  .prow
        BSR  newline

        LEA  r1, [s_trace]
        BSR  puts
        LEA  r2, [mat_c]
        MOV  r1, #0
        MOV  r3, #N
.trace: ADD  r1, [r2]           ; C[i][i]: ROW + 4 bytes apart
        ADD  r2, #ROW + 4
        DBNZ r3, .trace
        BSR  print_s32
        BSR  newline

        ; The Fletcher sums are kept in 32 bits and only their low halves
        ; printed: (a + b) mod 2^16 is the low half of the 32-bit sum, so
        ; masking at every step would change nothing.
        LEA  r1, [s_sum]
        BSR  puts
        LEA  r8, [mat_c]
        MOV  r9, #0             ; r9 = sum of the words
        MOV  r10, #0            ; r10 = s1
        MOV  r11, #0            ; r11 = s2
.sum:   ADD  r10, half [r8]     ; low half
        ADD  r11, r10
        ADD  r10, half [r8 + 2] ; high half
        ADD  r11, r10
        ADD  r9, [r8]+          ; the whole word, and on to the next
        CMP  r8, #mat_c + ROW * N
        BNE  .sum
        MOV  r1, r9
        MOV  r2, #8
        BSR  print_hex
        BSR  space
        MOV  r1, r10
        MOV  r2, #4
        BSR  print_hex
        BSR  space
        MOV  r1, r11
        MOV  r2, #4
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
