; queens: count the solutions of the 8 queens problem by backtracking with
; bitmasks (bit i = column i), and print the first solution found, which is
; the first in lowest-column-first order.
;
; solve keeps three masks for the row it is filling: the columns that are
; still free, and the squares attacked along the two diagonals. Going down a
; row, a queen's diagonals move one column left and one column right, which
; is a shift of each diagonal mask. "No free column left" is the same as
; "all N rows filled", so that test also detects a solution.

        .include "lib/start.s"

N = 8

; r13 = solutions found so far, for the whole search.
main:   SAVE r8-r13
        MOV  r13, #0
        LEA  r1, [cur]          ; row 0
        MOV  r2, #(1 << N) - 1  ; every column free,
        MOV  r3, #0             ; no diagonals attacked
        MOV  r4, #0
        BSR  solve

        LEA  r1, [s_count]
        BSR  puts
        MOV  r1, r13
        BSR  print_u32
        BSR  newline

        LEA  r1, [s_first]      ; the first solution's columns, numbered from 1
        BSR  puts
        LEA  r8, [first]
.col:   BSR  space
        MOV  r2, [r8]+          ; the queen's bit
        CLZ  r2, r2             ; bit number = 31 - CLZ, so the column
        MOV  r1, #32            ; numbered from 1 is 32 - CLZ
        SUB  r1, r2
        BSR  print_u32
        CMP  r8, #first + 4 * N
        BNE  .col
        BSR  newline

        LEA  r8, [first]        ; and as a board
.row:   MOV  r10, [r8]+         ; the queen's bit, shifted out square by square
        MOV  r11, #N
.sq:    MOV  r1, #'.'
        LSR  r10, #1            ; C = queen on this square
        BCC  .put
        MOV  r1, #'Q'
.put:   BSR  putc
        DEC  r11
        BEQ  .eol
        BSR  space
        BRA  .sq
.eol:   BSR  newline
        CMP  r8, #first + 4 * N
        BNE  .row
        RESTORE r8-r13
        RET

; solve: r1 = &cur[row], r2 = columns still free, r3 / r4 = squares in this
; row attacked along the two diagonals. Counts the solutions below this
; point in r13; the first complete one is copied to `first`.
solve:  TST  r2, r2
        BEQ  .found             ; no free column: all rows have a queen
        SAVE r8-r12
        MOV  r8, r1
        MOV  r9, r2
        MOV  r10, r3
        MOV  r11, r4
        MOV  r12, r2            ; r12 = free squares in this row
        BIC  r12, r3
        BIC  r12, r4
        BEQ  .done
.try:   NEG  r1, r12            ; the lowest free square: x & -x
        AND  r1, r12
        BIC  r12, r1
        MOV  [r8], r1
        MOV  r2, r9             ; next row: that column is taken,
        BIC  r2, r1
        MOV  r3, r10            ; and its diagonals move one column each way
        OR   r3, r1
        LSL  r3, #1
        MOV  r4, r11
        OR   r4, r1
        LSR  r4, #1
        LEA  r1, [r8 + 4]
        BSR  solve
        TST  r12, r12
        BNE  .try
.done:  RESTORE r8-r12
        RET

.found: INC  r13
        CMP  r13, #1
        BEQ  .first
        RET
.first: LEA  r1, [first]        ; the first solution: keep it
        LEA  r2, [cur]
        MOV  r3, #4 * N
        BRA  memcpy             ; tail call

s_count: .asciz "solutions: "
s_first: .asciz "first:"
        .align 2

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/string.s"

        .align 4
cur:    .space 4 * N            ; the queen's column bit in each row, while searching
first:  .space 4 * N
