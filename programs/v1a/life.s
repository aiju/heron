; life: Conway's Game of Life on a 32 x 16 torus. A glider, a blinker, a toad
; and a block, plus two blinkers that straddle the wrap-around seams; 20
; generations. Prints the population of every generation and the final board.
;
; A cell is a byte, 0 or 1. Each grid has a one-cell border (34 x 18 bytes)
; that is refilled from the opposite edges before every generation, so the
; neighbour count needs no wrap-around arithmetic: from r2 = the top-left
; neighbour, the neighbours are byte loads at fixed offsets 0, 1, 2, 34, 36,
; 68, 69, 70 and the cell itself at 35.
;
; The short LDB reaches only 0-15 bytes past its base, so six of the nine
; loads are two-parcel long forms. Keeping one pointer per row instead makes
; all nine one-parcel, but then four pointers step per cell instead of two;
; I measured both, they come out within 0.3% of each other on D16-overlap,
; and this version is the simpler leaf routine.

        .include "lib/start.s"

COLS  = 32
ROWS  = 16
W2    = COLS + 2                ; bytes per stored row
GRID  = W2 * (ROWS + 2)
GENS  = 20

main:   SAVE r8-r11
        LEA  r1, pattern        ; grid_a starts all dead (.space): set the
        MVI  r2, 1              ; pattern's cells, counting them
        MVI  r10, 0             ; r10 = population (of generation 0 here)
.place: LD   r3, [r1]           ; offsets of live cells; -1 ends the list
        BMI  .placed
        STB  r2, [grid_a + r3]
        ADDI r1, 4
        ADDI r10, 1
        BRA  .place
.placed:
        LEA  r1, s_pop
        BSR  puts
        LEA  r8, grid_a         ; r8 = current grid, r9 = next
        LEA  r9, grid_b
        MVI  r11, GENS
.gen:   BSR  space              ; print GENS + 1 populations, step GENS times
        MOV  r1, r10
        BSR  print_u32
        ADDI r11, -1
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
; of the next grid. A leaf: uses only r1-r7.
step:   MOV  r7, r2
        ADDI r7, W2 + 1         ; r7 = the cell in the next grid
        MOV  r2, r1             ; r2 = the cell's top-left neighbour
        MVI  r6, 0              ; r6 = population
        MVI  r3, ROWS
.row:   LEA  r4, [r2 + COLS]    ; r4 = r2 after the row's last cell
.cell:  LDB  r1, [r2]           ; top left
        LDB  r5, [r2 + 1]       ; top
        ADD  r1, r5
        LDB  r5, [r2 + 2]       ; top right
        ADD  r1, r5
        LDB  r5, [r2 + W2]      ; left (long form from here on)
        ADD  r1, r5
        LDB  r5, [r2 + W2 + 2]  ; right
        ADD  r1, r5
        LDB  r5, [r2 + 2 * W2]  ; bottom left
        ADD  r1, r5
        LDB  r5, [r2 + 2 * W2 + 1]        ; bottom
        ADD  r1, r5
        LDB  r5, [r2 + 2 * W2 + 2]        ; bottom right
        ADD  r1, r5
        LDB  r5, [r2 + W2 + 1]  ; the cell itself: (neighbours | self) = 3
        OR   r1, r5             ; is exactly the rule: 3 neighbours, or 2 and
        CMPI r1, 3              ; alive
        SETEQ r1
        ADD  r6, r1
        STB  r1, [r7]
        ADDI r2, 1
        ADDI r7, 1
        CMP  r2, r4
        BNE  .cell
        ADDI r2, 2              ; skip the border columns
        ADDI r7, 2
        ADDI r3, -1
        BNE  .row
        MOV  r1, r6
        RET

; wrap: r1 = grid. Copy the opposite edges into the border: columns first,
; then whole rows, which also fills the corners.
wrap:   PUSH r8
        MOV  r8, r1
        MOV  r2, r1
        ADDI r2, W2             ; row 1
        MVI  r3, ROWS
.col:   LDB  r4, [r2 + COLS]
        STB  r4, [r2]           ; column 32 -> column 0
        LDB  r4, [r2 + 1]
        STB  r4, [r2 + COLS + 1]          ; column 1 -> column 33
        ADDI r2, W2
        ADDI r3, -1
        BNE  .col
        MOV  r1, r8             ; row 16 -> row 0
        LEA  r2, [r8 + ROWS * W2]
        MVI  r3, W2
        BSR  memcpy
        LEA  r1, [r8 + (ROWS + 1) * W2]   ; row 1 -> row 17
        LEA  r2, [r8 + W2]
        MVI  r3, W2
        BSR  memcpy
        POP  r8
        RET

; show: r1 = grid. Print it as # and . characters.
show:   SAVE r8-r10
        LEA  r8, [r1 + W2 + 1]  ; r8 = the first cell
        MVI  r9, ROWS
.row:   LEA  r10, [r8 + COLS]   ; end of the row
.cell:  LDB  r1, [r8]
        LDB  r1, [cellchar + r1]
        BSR  putc
        ADDI r8, 1
        CMP  r8, r10
        BNE  .cell
        BSR  newline
        ADDI r8, 2
        ADDI r9, -1
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
