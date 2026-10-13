; queens: count the solutions of the 8 queens problem by backtracking
; (bitmasks for the attacked columns and diagonals) and print the first one.

        .include "lib/start.s"

N = 8

main:   PUSH r8
        PUSH r9
        MVI  r1, 0              ; row 0 (counted in bytes: row * 2)
        MVI  r2, 0              ; no columns or diagonals attacked yet
        MVI  r3, 0
        MVI  r4, 0
        BSR  solve
        LI   r1, #s_count
        CALL puts
        LD   r1, [count]
        CALL print_u16
        CALL newline

        LI   r1, #s_first       ; the columns, numbered from 1
        CALL puts
        LI   r8, #first
.col:   CALL space
        LD   r1, [r8]
        BSR  bitnum
        INC  r1
        CALL print_u16
        ADDI r8, 2
        CMP  r8, #first + 2 * N
        BLO  .col
        CALL newline

        LI   r8, #first         ; and as a board
.row:   LD   r9, [r8]           ; queen's bit in this row
        MVI  r2, 1              ; column bit
.sq:    MVI  r1, '.'
        TST  r2, r9
        BEQ  .put
        MVI  r1, 'Q'
.put:   PUSH r2
        CALL putc
        POP  r2
        SHL  r2
        CMP  r2, #1 << N
        BEQ  .eol
        PUSH r2
        CALL space
        POP  r2
        BRA  .sq
.eol:   CALL newline
        ADDI r8, 2
        CMP  r8, #first + 2 * N
        BLO  .row
        POP  r9
        POP  r8
        RET

; solve: r1 = row * 2, r2/r3/r4 = columns / left diagonals / right diagonals
; attacked in this row (bit i = column i). Counts the solutions below this
; point; the first complete one is copied to `first`.
solve:  CMPI r1, 2 * N
        BNE  .place
        LD   r5, [count]        ; a solution
        BNE  .counted
        MVI  r7, 0              ; the first one: keep it
.copy:  LD   r2, [cur + r7]
        ST   r2, [first + r7]
        ADDI r7, 2
        CMPI r7, 2 * N
        BNE  .copy
.counted:
        INC  r5
        ST   r5, [count]
        RET
.place: PUSH r8
        PUSH r9
        PUSH r10
        PUSH r11
        PUSH r12
        MOV  r8, r1
        MOV  r9, r2
        MOV  r10, r3
        MOV  r11, r4
        MOV  r12, r2            ; r12 = free squares in this row
        OR   r12, r3
        OR   r12, r4
        NOT  r12
        AND  r12, #(1 << N) - 1
.try:   BEQ  .done
        NEG  r1, r12            ; lowest free square: x & -x (the unary ops
        AND  r1, r12            ; take a separate source, so no copy needed)
        BIC  r12, r1
        ST   r1, [cur + r8]
        MOV  r2, r9             ; next row: this column is attacked,
        OR   r2, r1
        MOV  r3, r10            ; and the diagonals move one column each way
        OR   r3, r1
        SHL  r3
        MOV  r4, r11
        OR   r4, r1
        SHR  r4
        MOV  r1, r8
        ADDI r1, 2
        BSR  solve
        TST  r12, r12
        BRA  .try
.done:  POP  r12
        POP  r11
        POP  r10
        POP  r9
        POP  r8
        RET

; bitnum: r1 = a word with one bit set -> r1 = the number of that bit.
bitnum: MVI  r2, -1
.loop:  INC  r2
        SHR  r1
        BNE  .loop
        MOV  r1, r2
        RET

count:  .word 0
cur:    .space 2 * N            ; queen's column bit for each row, while searching
first:  .space 2 * N
s_count: .asciz "solutions: "
s_first: .asciz "first:"

        .include "lib/console.s"
        .include "lib/print.s"
