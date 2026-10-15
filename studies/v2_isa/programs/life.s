; life: Conway's Game of Life on a 32 x 16 torus. A glider, a blinker, a toad
; and a block, plus two blinkers that straddle the wrap-around seams; 20
; generations. Prints the population of every generation and the final board.
;
; A cell is a byte, 0 or 1. Each grid has a one-cell border (34 x 18 bytes)
; that is refilled from the opposite edges before every generation, so the
; neighbour count needs no wrap-around arithmetic. The first load takes the
; top-left neighbour and steps r2 on to the top one ([r2]+); from there the
; other seven are at fixed offsets 0, 1, 33, 35, 67, 68, 69 and the cell
; itself at 34. Each is a memory operand of an ADD (or the OR), so the count
; is one instruction per neighbour.

        .include "lib/start.s"

COLS  = 32
ROWS  = 16
W2    = COLS + 2                ; bytes per stored row
GRID  = W2 * (ROWS + 2)
GENS  = 20

main:   SAVE r8-r11
        LEA  r1, [pattern]      ; grid_a starts all dead (.space): set the
        MOV  r2, #1             ; pattern's cells, counting them
        MOV  r10, #0            ; r10 = population (of generation 0 here)
.place: MOVS r3, [r1]+          ; offsets of live cells; -1 ends the list
        BMI  .placed
        MOV  byte [grid_a + r3], r2
        INC  r10
        BRA  .place
.placed:
        LEA  r1, [s_pop]
        BSR  puts
        LEA  r8, [grid_a]       ; r8 = current grid, r9 = next
        LEA  r9, [grid_b]
        MOV  r11, #GENS
.gen:   BSR  space              ; print GENS + 1 populations, step GENS times
        MOV  r1, r10
        BSR  print_u32
        DEC  r11
        BMI  .done
        MOV  r1, r8
        BSR  wrap
        MOV  r1, r8
        MOV  r2, r9
        BSR  step
        MOV  r10, r1
        MOV  r1, r8             ; swap the grids
        MOV  r8, r9
        MOV  r9, r1
        BRA  .gen
.done:  BSR  newline
        MOV  r1, r8
        BSR  show
        RESTORE r8-r11
        RET

; step: r1 = current grid (border filled), r2 = next grid -> r1 = population
; of the next grid. Uses only r1-r6.
step:   LEA  r3, [r2 + W2 + 1]  ; r3 = the cell in the next grid
        MOV  r2, r1             ; r2 = the cell's top-left neighbour
        MOV  r6, #0             ; r6 = population
        MOV  r4, #ROWS
.row:   LEA  r5, [r2 + COLS]    ; r5 = r2 after the row's last cell
.cell:  MOV  r1, byte [r2]+     ; top left; r2 moves on to the top neighbour
        ADD  r1, byte [r2]      ; top
        ADD  r1, byte [r2 + 1]  ; top right
        ADD  r1, byte [r2 + W2 - 1]       ; left
        ADD  r1, byte [r2 + W2 + 1]       ; right
        ADD  r1, byte [r2 + 2 * W2 - 1]   ; bottom left
        ADD  r1, byte [r2 + 2 * W2]       ; bottom
        ADD  r1, byte [r2 + 2 * W2 + 1]   ; bottom right
        OR   r1, byte [r2 + W2]           ; the cell itself: (neighbours | self)
        CMP  r1, #3                       ; = 3 is exactly the rule: 3 neighbours,
        SETEQ r1                          ; or 2 and alive
        ADD  r6, r1
        MOV  byte [r3]+, r1
        CMP  r2, r5
        BNE  .cell
        ADD  r2, #2             ; skip the border columns
        ADD  r3, #2
        DEC  r4
        BNE  .row
        MOV  r1, r6
        RET

; wrap: r1 = grid. Copy the opposite edges into the border: columns first,
; then whole rows, which also fills the corners.
wrap:   MOV  -[sp], r8
        MOV  r8, r1
        LEA  r2, [r1 + W2]      ; row 1
        MOV  r3, #ROWS
.col:   MOV  r4, byte [r2 + COLS]
        MOV  byte [r2], r4      ; column 32 -> column 0
        MOV  r4, byte [r2 + 1]
        MOV  byte [r2 + COLS + 1], r4     ; column 1 -> column 33
        ADD  r2, #W2
        DEC  r3
        BNE  .col
        MOV  r1, r8             ; row 16 -> row 0
        LEA  r2, [r8 + ROWS * W2]
        MOV  r3, #W2
        BSR  memcpy
        LEA  r1, [r8 + (ROWS + 1) * W2]   ; row 1 -> row 17
        LEA  r2, [r8 + W2]
        MOV  r3, #W2
        BSR  memcpy
        MOV  r8, [sp]+
        RET

; show: r1 = grid. Print it as # and . characters.
show:   SAVE r8-r10
        LEA  r8, [r1 + W2 + 1]  ; r8 = the first cell
        MOV  r9, #ROWS
.row:   LEA  r10, [r8 + COLS]   ; end of the row
.cell:  MOV  r1, byte [r8]+
        MOV  r1, byte [cellchar + r1]
        BSR  putc
        CMP  r8, r10
        BNE  .cell
        BSR  newline
        ADD  r8, #2
        DEC  r9
        BNE  .row
        RESTORE r8-r10
        RET

; Live cells as offsets into the grid: (row + 1) * W2 + (col + 1).
        .align 4
pattern:
        .word 1*W2+2, 2*W2+3, 3*W2+1, 3*W2+2, 3*W2+3            ; glider at (0,0), heading down-right
        .word 9*W2+24, 9*W2+25, 9*W2+26                         ; blinker
        .word 13*W2+8, 13*W2+9, 13*W2+10, 14*W2+7, 14*W2+8, 14*W2+9  ; toad
        .word 4*W2+28, 4*W2+29, 5*W2+28, 5*W2+29                ; block
        .word 8*W2+32, 8*W2+1, 8*W2+2                           ; blinker across the left/right seam
        .word 16*W2+21, 1*W2+21, 2*W2+21                        ; blinker across the top/bottom seam
        .word -1
s_pop:  .asciz "population:"
cellchar: .ascii ".#"
        .align 2

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/string.s"

        .align 4
grid_a: .space GRID
grid_b: .space GRID
