; life: Conway's Game of Life on a 32 x 16 torus. A glider, a blinker, a toad
; and a block; 20 generations. Prints the population of every generation and
; the final board.
;
; Each grid has a one-cell border (34 x 18 bytes) that is refilled from the
; opposite edges before every generation, so the neighbour loads need no
; wrap-around arithmetic: from p = the top-left neighbour they are at fixed
; offsets 0, 1, 2, 34, 36, 68, 69, 70.

        .include "lib/start.s"

COLS  = 32
ROWS  = 16
W2    = COLS + 2                ; bytes per stored row
GRID  = W2 * (ROWS + 2)
GENS  = 20

main:   PUSH r8
        PUSH r9
        PUSH r10

        LI   r1, #grid_a        ; clear, then place the pattern
        MVI  r2, 0
        LI   r3, #GRID
        CALL memset
        LI   r2, #pattern
.place: LD   r3, [r2]           ; offsets of live cells, -1 ends the list
        CMPI r3, -1
        BEQ  .placed
        MVI  r4, 1
        STB  r4, [grid_a + r3]
        ADDI r2, 2
        BRA  .place
.placed:
        LI   r1, #s_pop
        CALL puts
        LI   r8, #grid_a        ; r8 = current, r9 = next
        LI   r9, #grid_b
        MVI  r10, GENS
.gen:   CALL space
        MOV  r1, r8
        BSR  population
        CALL print_u16
        MOV  r1, r8
        BSR  wrap
        MOV  r1, r8
        MOV  r2, r9
        BSR  step
        MOV  r1, r8             ; swap the grids
        MOV  r8, r9
        MOV  r9, r1
        DEC  r10
        BNE  .gen
        CALL space
        MOV  r1, r8
        BSR  population
        CALL print_u16
        CALL newline
        MOV  r1, r8
        BSR  show

        POP  r10
        POP  r9
        POP  r8
        RET

; wrap: r1 = grid. Copy the opposite edges into the border.
wrap:   PUSH r8
        MOV  r8, r1
        MOV  r2, r1             ; columns first, for rows 1-16:
        ADDI r2, W2
        MVI  r3, ROWS
.col:   LDB  r4, [r2 + COLS]    ;   column 32 -> column 0
        STB  r4, [r2]
        LDB  r4, [r2 + 1]       ;   column 1 -> column 33
        STB  r4, [r2 + COLS + 1]
        ADDI r2, W2
        DEC  r3
        BNE  .col
        MOV  r1, r8             ; then whole rows, which also fills the corners:
        MOV  r2, r8             ;   row 16 -> row 0
        ADD  r2, #ROWS * W2
        MVI  r3, W2
        CALL memcpy
        MOV  r1, r8             ;   row 1 -> row 17
        ADD  r1, #(ROWS + 1) * W2
        MOV  r2, r8
        ADDI r2, W2
        MVI  r3, W2
        CALL memcpy
        POP  r8
        RET

; step: r1 = current grid (border filled), r2 = next grid.
step:   PUSH r8
        PUSH r9
        PUSH r10
        PUSH r11
        MOV  r8, r1             ; r8 = top-left neighbour of the cell
        MOV  r9, r2
        ADDI r9, W2 + 1         ; r9 = the cell in the next grid
        MVI  r10, ROWS
.row:   MVI  r11, COLS
.cell:  LDB  r1, [r8]
        LDB  r2, [r8 + 1]
        ADD  r1, r2
        LDB  r2, [r8 + 2]
        ADD  r1, r2
        LDB  r2, [r8 + W2]
        ADD  r1, r2
        LDB  r2, [r8 + W2 + 2]
        ADD  r1, r2
        LDB  r2, [r8 + 2 * W2]
        ADD  r1, r2
        LDB  r2, [r8 + 2 * W2 + 1]
        ADD  r1, r2
        LDB  r2, [r8 + 2 * W2 + 2]
        ADD  r1, r2
        LDB  r2, [r8 + W2 + 1]  ; the cell itself
        OR   r1, r2             ; (neighbours | self) == 3 is exactly the rule:
        ADDI r1, -3             ; 3 neighbours, or 2 and alive
        NEG  r1                 ; C = (r1 == 0): there is no "set on condition",
        MVI  r1, 0              ; but NEG's carry is a zero test and ADC r0
        ADC  r1, r0             ; turns it into 0 or 1 without a branch
        STB  r1, [r9]
        INC  r8
        INC  r9
        DEC  r11
        BNE  .cell
        ADDI r8, 2              ; skip the border columns
        ADDI r9, 2
        DEC  r10
        BNE  .row
        POP  r11
        POP  r10
        POP  r9
        POP  r8
        RET

; population: r1 = grid -> r1 = number of live cells.
population:
        ADDI r1, W2 + 1
        MVI  r2, 0
        MVI  r3, ROWS
.row:   MVI  r4, COLS
.cell:  LDB  r5, [r1]
        ADD  r2, r5
        INC  r1
        DEC  r4
        BNE  .cell
        ADDI r1, 2
        DEC  r3
        BNE  .row
        MOV  r1, r2
        RET

; show: r1 = grid. Print it as # and . characters.
show:   PUSH r8
        PUSH r9
        PUSH r10
        MOV  r8, r1
        ADDI r8, W2 + 1
        MVI  r9, ROWS
.row:   MVI  r10, COLS
.cell:  MVI  r1, '.'
        LDB  r2, [r8]
        BEQ  .out
        MVI  r1, '#'
.out:   CALL putc
        INC  r8
        DEC  r10
        BNE  .cell
        CALL newline
        ADDI r8, 2
        DEC  r9
        BNE  .row
        POP  r10
        POP  r9
        POP  r8
        RET

; Live cells as offsets into the grid: (row + 1) * W2 + (col + 1).
pattern:
        .word 1*W2+2, 2*W2+3, 3*W2+1, 3*W2+2, 3*W2+3            ; glider at (0,0), heading down-right
        .word 9*W2+24, 9*W2+25, 9*W2+26                         ; blinker
        .word 13*W2+8, 13*W2+9, 13*W2+10, 14*W2+7, 14*W2+8, 14*W2+9  ; toad
        .word 4*W2+28, 4*W2+29, 5*W2+28, 5*W2+29                ; block
        .word 8*W2+32, 8*W2+1, 8*W2+2                           ; blinker across the left/right seam
        .word 16*W2+21, 1*W2+21, 2*W2+21                        ; blinker across the top/bottom seam
        .word -1
s_pop:  .asciz "population:"

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/string.s"

grid_a: .space GRID
grid_b: .space GRID
