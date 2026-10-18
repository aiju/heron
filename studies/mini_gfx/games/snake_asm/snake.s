; Snake in draft 2 assembly: the game of ../snake (the C one) written by
; hand, with as little C as the runtime needs. main.c calls snake_main;
; this calls the runtime's video_init, video_wait, input_init,
; input_next, video_ticks, rt_shot and the perf_ functions (rt/) by the
; C calling convention (arguments in r1-r4, r0-r7 the caller's, the
; return address in r7). Everything else is here: drawing straight into
; the framebuffer's words, text from the cell font's data, the palette
; and the descriptors through their registers and tables, the game and
; its autopilot. It uses nothing of the graphics library.
;
; The video as the C game has it: M1 used as 320 x 240 x 8, each row on
; two lines (two descriptors); the body's colours rotated through the
; palette; the banner shown by pointing lines at another buffer; the
; crash's shake by moving the descriptors; the title rippling. A pixel is
; a byte in L0 and spread over the word's bytes in L1 (RFC 0042, 4), so
; the colours' words and the pixels' masks come from tables built for
; the board's layout at the start, and all the drawing goes through
; them: both layouts work. In the blk variant (main.c's snake_blk) the
; big fills and copies use FILL and COPY.
;
; Registers: r14 points at the game's variables throughout (mode E,
; [r14 + 4R], a one-parcel operand); the leaf routines use r0-r6 and
; save anything else they use; r7 is the return address, so a routine
; that calls saves it. Several leaves end in a jump to fill_rect, which
; returns for them.

        .global _snake_main
        .far _font_cell8

; ---- the machine ----
FB          = 0x202000          ; the framebuffer: 320 x 240 bytes in bank 1
BANNER      = 0x214C00          ; the messages' banner: 320 x 48
PBANNER     = 0x218800          ; the pause's banner
BG          = 0x21C400          ; the empty board, for the measurements
FB_DESC     = 0x800             ; FB's word in bank 1: its row 0's descriptor
BANNER_DESC = 0x5300
PBANNER_DESC = 0x6200
TABLE0      = 0x2000B0          ; table 0, picture line 0's descriptor (T = 44)
VID_PAL     = 0xF0000400
CONSOLE     = 0xFFFFFF00

; ---- the game ----
PITCH       = 320               ; bytes a row
GW          = 40                ; the grid in cells, the walls included
GH          = 27
GY          = 24                ; the grid's top on the screen
RING        = 1024
BANNER_Y    = 96
BANNER_H    = 48

G_FREE      = 0
G_WALL      = 1
G_SNAKE     = 2
G_FOOD      = 3

K_UP        = 0x11
K_ESC       = 27
EV_KEY      = 1

; palette entries, as the C game's
C_GRASS0    = 16
C_GRASS1    = 17
C_WALL      = 18
C_WALL_HI   = 19
C_BAR       = 20
C_BAR_TEXT  = 21
C_BAR_DIM   = 22
C_BAR_LINE  = 23
C_FOOD      = 24
C_FOOD_DK   = 25
C_LEAF      = 26
C_FOOD_HI   = 27
C_HEAD      = 28
C_EYE       = 29                ; C_PUPIL is the next
C_BLINK     = 31
C_BODY      = 32                ; 16 entries, rotated
C_BANNER    = 48
C_BANNER_HI = 49
C_BANNER_TX = 50
C_DEAD      = 51
C_TITLE_BG  = 52

; the variables at r14
S_HEAD      = 0
S_TAIL      = 4
S_DIR       = 8
S_GROW      = 12
S_SCORE     = 16
S_BEST      = 20
S_FOODS     = 24
S_PERIOD    = 28
S_AUTO      = 32
S_ALIVE     = 36
S_PAUSED    = 40
S_STEPS     = 44
S_FX        = 48
S_FY        = 52
S_FRAME     = 56
S_TICK      = 60

        .text

; ======================================================================
; the start
; ======================================================================

_snake_main:
        SAVE r7-r14
        LEA  r14, [sn_state]
        CALL _input_init
        MOV  r1, #1             ; M1
        MOV  r2, #0
        CALL _video_init
        BSR  tables
        BSR  set_palette
        BSR  make_food
        LEA  r1, [s_paused]
        LEA  r2, [s_goon]
        MOV  r3, #PBANNER
        BSR  draw_banner
        BSR  title
        BSR  play
        BSR  game_over
        BSR  measure
        LEA  r1, [s_done]
        BSR  say
.idle:  CALL _video_wait
        BRA  .idle

; say: the string at r1 on the console. Leaf.
say:    MOVS r0, byte [r1]+
        BEQ  .x
        MOV  byte [CONSOLE], r0
        BRA  say
.x:     RET

; ======================================================================
; the tables for the layout
; ======================================================================

; pmask[p], pixel p's bits; from[p], pixels p..3 (from[4] = 0); nib[v],
; the pixels whose bits are set in v (a nibble of a glyph's row);
; solid[c], colour c in all four pixels, from the planes (bit i of every
; pixel). L0 and L1 differ only in the planes and the pixels' masks.
tables: LEA  r4, [sn_planes0]
        LEA  r5, [sn_pmask0]
        MOVS r0, [_board_layout]
        BEQ  .go
        LEA  r4, [sn_planes1]
        LEA  r5, [sn_pmask1]
.go:    LEA  r6, [sn_pmask]
        MOV  r3, #4
.pm:    MOV  r0, [r5]+
        MOV  [r6]+, r0
        DBNZ r3, .pm
        ; from[p] = from[p + 1] | pmask[p]
        LEA  r6, [sn_from + 16]
        MOV  r0, #0
        MOV  [r6], r0
        MOV  r3, #4
.fr:    OR   r0, -[r5]
        MOV  -[r6], r0
        DBNZ r3, .fr
        ; nib[v]
        LEA  r6, [sn_nib]
        MOV  r1, #0
.nv:    MOV  r2, #0
        MOV  r3, #1
        LEA  r5, [sn_pmask]
.nb:    MOV  r0, [r5]+
        TST  r1, r3
        BEQ  .nz
        OR   r2, r0
.nz:    LSL  r3, #1
        CMP  r3, #16
        BNE  .nb
        MOV  [r6]+, r2
        INC  r1
        CMP  r1, #16
        BNE  .nv
        ; solid[c], c < 64
        LEA  r6, [sn_solid]
        MOV  r1, #0
.sc:    MOV  r2, #0
        MOV  r3, #1
        MOV  r5, r4
.sb:    MOV  r0, [r5]+
        TST  r1, r3
        BEQ  .sz
        OR   r2, r0
.sz:    LSL  r3, #1
        CMP  r3, #256
        BNE  .sb
        MOV  [r6]+, r2
        INC  r1
        CMP  r1, #64
        BNE  .sc
        RET

; the food's image and mask in the screen's format, from its art
make_food:
        LEA  r1, [sn_food_art]
        LEA  r2, [sn_food_img]
        LEA  r3, [sn_food_mask]
        MOV  r4, #0             ; the pixel, 0-63
.p:     MOVS r5, byte [r1]+
        BEQ  .n
        MOV  r5, [sn_solid + r5*4]
        MOV  r6, r4
        AND  r6, #3
        MOV  r6, [sn_pmask + r6*4]
        AND  r5, r6
        MOV  r0, r4
        LSR  r0, #2             ; the word, two a row
        LSL  r0, #2
        OR   r5, [r2 + r0]
        MOV  [r2 + r0], r5
        OR   r6, [r3 + r0]
        MOV  [r3 + r0], r6
.n:     INC  r4
        CMP  r4, #64
        BNE  .p
        RET

; ======================================================================
; drawing, in the buffer at sn_target (320 bytes a row)
; ======================================================================

; fill_rect: r1 x, r2 y, r3 w, r4 h (w, h > 0), r5 a colour: the first
; word under lmask, the whole words, the last under rmask. Leaf; saves
; r8-r10.
fill_rect:
        SAVE r8-r10
        MOV  r5, [sn_solid + r5*4]
        MOV  r0, r2
        LSL  r0, #8
        LSL  r2, #6
        ADD  r2, r0
        ADD  r2, [sn_target]    ; r2: the row
        ADD  r3, r1
        DEC  r3                 ; r3: the last pixel
        MOV  r6, r3
        LSR  r6, #2
        MOV  r0, r1
        LSR  r0, #2
        SUB  r6, r0             ; r6: the words after the first
        LSL  r0, #2
        ADD  r2, r0             ; r2: the first word
        AND  r1, #3
        MOV  r1, [sn_from + r1*4]       ; r1: lmask
        AND  r3, #3
        MOV  r3, [sn_from + 4 + r3*4]
        NOT  r3                         ; r3: rmask
        MOV  r8, #PITCH
        TST  r6, r6
        BNE  .wide
        AND  r1, r3
        MOV  r0, r1
.one:   MOV  r9, [r2]
        MERGE r9, r5, r0
        MOV  [r2], r9
        ADD  r2, r8
        DBNZ r4, .one
        RESTORE r8-r10
        RET
.wide:  MOV  r0, r6
        LSL  r0, #2
        SUB  r8, r0             ; r8: from a row's last word to the next row's first
.row:   MOV  r0, r1
        MOV  r9, [r2]
        MERGE r9, r5, r0
        MOV  [r2]+, r9
        MOV  r10, r6
        DEC  r10
        BEQ  .last
.mid:   MOV  [r2]+, r5
        DBNZ r10, .mid
.last:  MOV  r0, r3
        MOV  r9, [r2]
        MERGE r9, r5, r0
        MOV  [r2], r9
        ADD  r2, r8
        DBNZ r4, .row
        RESTORE r8-r10
        RET

; pixel: r1 x, r2 y, r5 a colour. Leaf.
pixel:  MOV  r5, [sn_solid + r5*4]
        MOV  r0, r2
        LSL  r0, #8
        LSL  r2, #6
        ADD  r2, r0
        ADD  r2, [sn_target]
        MOV  r0, r1
        AND  r0, #-4
        ADD  r2, r0
        AND  r1, #3
        MOV  r0, [sn_pmask + r1*4]
        MOV  r3, [r2]
        MERGE r3, r5, r0
        MOV  [r2], r3
        RET

; text: r1 x (a multiple of 4), r2 y, r3 the string (' '-'~', ending in
; 0), r4 fg, r5 bg: the cell font, opaque; each glyph row's byte is two
; words, a nibble each through nib: bg ^ ((fg ^ bg) & mask). Leaf;
; saves r8-r12.
text:   SAVE r8-r12
        MOV  r4, [sn_solid + r4*4]
        MOV  r5, [sn_solid + r5*4]
        XOR  r4, r5             ; r4: fg ^ bg
        MOV  r0, r2
        LSL  r0, #8
        LSL  r2, #6
        ADD  r2, r0
        ADD  r2, [sn_target]
        ADD  r2, r1             ; r2: the glyph's top left word
        LEA  r12, [sn_nib]
.ch:    MOVS r0, byte [r3]+
        BEQ  .done
        SUB  r0, #32
        LSL  r0, #4
        MOV  r6, #_font_cell8
        ADD  r6, r0             ; r6: the glyph's 16 rows
        MOV  r8, r2
        MOV  r9, #16
.row:   MOV  r10, byte [r6]+
        MOV  r11, r10
        AND  r11, #15
        MOV  r11, [r12 + r11*4]
        AND  r11, r4
        XOR  r11, r5
        MOV  [r8], r11
        LSR  r10, #4
        MOV  r10, [r12 + r10*4]
        AND  r10, r4
        XOR  r10, r5
        MOV  [r8 + 4], r10
        ADD  r8, #PITCH
        DEC  r9
        BNE  .row
        ADD  r2, #8
        BRA  .ch
.done:  RESTORE r8-r12
        RET

; digits: r1 a number, r2 where its string ends (a 0 is written there),
; r3 the digits, r4 nonzero for spaces in front rather than zeros.
; Leaf; r2 is left at the string.
digits: MOV  r6, #10
        MOV  r5, #0
        MOV  byte [r2], r5
.d:     DIVU r0:r1, r6
        ADD  r0, #'0'
        DEC  r2
        MOV  byte [r2], r0
        DEC  r3
        BEQ  .x
        TST  r1, r1
        BNE  .d
        TST  r4, r4
        BEQ  .d
        MOV  r0, #' '
.sp:    DEC  r2
        MOV  byte [r2], r0
        DEC  r3
        BNE  .sp
.x:     RET

; block_text: r1 x, r2 y, r3 the string (capitals and spaces), r4 the
; dots' size, r5 a colour, or -1 for the body's rotating colours by
; place. A dot is a square inset by size / 8 (at least 1) and joined to
; the dots right of it and below it, so the letters look like the snake.
block_text:
        SAVE r7-r13
        MOV  r8, r1             ; r8: the letter's x
        MOV  r9, r2             ; r9: y
        MOV  r10, r3            ; r10: the string
        MOV  r11, r4            ; r11: the size
        MOV  [sn_bt_c], r5
        MOV  r0, r4
        LSR  r0, #3
        BNE  .in
        MOV  r0, #1
.in:    MOV  [sn_bt_in], r0
        MOV  r0, #0
        MOV  [sn_bt_i], r0
.letter:
        MOVS r0, byte [r10]+
        BEQ  .done
        CMP  r0, #' '
        BEQ  .next
        SUB  r0, #'A'
        MOV  r1, r0
        LSL  r1, #3
        SUB  r1, r0
        LEA  r13, [sn_letters + r1]     ; r13: the letter's 7 rows
        MOV  r12, #0                    ; r12: the row
.row:   MOV  r0, #0
        MOV  [sn_bt_col], r0
.dot:   MOV  r0, byte [r13 + r12]
        MOV  r1, [sn_bt_col]
        LSR  r0, r1
        TST  r0, #1
        BEQ  .skip
        ; the colour: given, or C_BODY + (15 - col - row - 6i) & 15
        MOVS r5, [sn_bt_c]
        BPL  .c
        MOV  r5, #15
        SUB  r5, r1
        SUB  r5, r12
        MOV  r0, [sn_bt_i]
        SUB  r5, r0
        AND  r5, #15
        ADD  r5, #C_BODY
        MOV  [sn_bt_dotc], r5
        BRA  .sq
.c:     MOV  [sn_bt_dotc], r5
        ; the square: (x + col * size + in, y + row * size + in), size - 2 in
.sq:    BSR  dot_xy             ; r1, r2: the dot's top left
        MOV  r0, [sn_bt_in]
        ADD  r1, r0
        ADD  r2, r0
        MOV  r3, r11
        SUB  r3, r0
        SUB  r3, r0
        MOV  r4, r3
        MOV  r5, [sn_bt_dotc]
        BSR  fill_rect
        ; joined to the right
        MOV  r0, byte [r13 + r12]
        MOV  r1, [sn_bt_col]
        INC  r1
        LSR  r0, r1
        TST  r0, #1
        BEQ  .down
        BSR  dot_xy
        MOV  r0, [sn_bt_in]
        ADD  r1, r11
        SUB  r1, r0
        ADD  r2, r0
        MOV  r3, r0
        ADD  r3, r0
        MOV  r4, r11
        SUB  r4, r0
        SUB  r4, r0
        MOV  r5, [sn_bt_dotc]
        BSR  fill_rect
        ; joined below
.down:  CMP  r12, #6
        BEQ  .skip
        MOV  r0, byte [r13 + r12 + 1]   ; the row below
        MOV  r1, [sn_bt_col]
        LSR  r0, r1
        TST  r0, #1
        BEQ  .skip
        BSR  dot_xy
        MOV  r0, [sn_bt_in]
        ADD  r1, r0
        ADD  r2, r11
        SUB  r2, r0
        MOV  r3, r11
        SUB  r3, r0
        SUB  r3, r0
        MOV  r4, r0
        ADD  r4, r0
        MOV  r5, [sn_bt_dotc]
        BSR  fill_rect
.skip:  MOV  r0, [sn_bt_col]
        INC  r0
        MOV  [sn_bt_col], r0
        CMP  r0, #5
        BNE  .dot
        INC  r12
        CMP  r12, #7
        BNE  .row
.next:  MOV  r0, r11
        MOV  r1, r0
        LSL  r0, #2
        LSL  r1, #1
        ADD  r0, r1
        ADD  r8, r0             ; the next letter: 6 dots on
        MOV  r0, [sn_bt_i]
        ADD  r0, #6
        MOV  [sn_bt_i], r0      ; 6 a letter, for the colours
        BRA  .letter
.done:  RESTORE r7-r13
        RET

; dot_xy: block_text's dot's top left in r1, r2 (r8 + col * size,
; r9 + row * size). Leaf, r0-r2.
dot_xy: MOV  r1, [sn_bt_col]
        MULU r0:r1, r11
        ADD  r1, r8
        MOV  r2, r12
        MULU r0:r2, r11
        ADD  r2, r9
        RET

; ---- the cells: (r1, r2) a cell of the grid ----

; grass: the cell's grass. Leaf (ends in fill_rect).
grass:  MOV  r5, r1
        XOR  r5, r2
        AND  r5, #1
        ADD  r5, #C_GRASS0
        LSL  r1, #3
        LSL  r2, #3
        ADD  r2, #GY
        MOV  r3, #8
        MOV  r4, #8
        BRA  fill_rect

; block: a segment, 6 x 6 in the cell, colour r5
block:  LSL  r1, #3
        INC  r1
        LSL  r2, #3
        ADD  r2, #GY + 1
        MOV  r3, #6
        MOV  r4, #6
        BRA  fill_rect

; bridge: the 2 pixels joining the cell to the next in direction r3, colour r5
bridge: LSL  r3, #4
        LEA  r6, [sn_bridges + r3]
        LSL  r1, #3
        ADD  r1, [r6]+
        LSL  r2, #3
        ADD  r2, #GY
        ADD  r2, [r6]+
        MOV  r3, [r6]+
        MOV  r4, [r6]
        BRA  fill_rect

; unstub: once the cell is gone, the half of its bridge left in the next
; cell (direction r3) back to that cell's grass
unstub: ADD  r1, [sn_dx + r3*4]
        ADD  r2, [sn_dy + r3*4]
        MOV  r5, r1
        XOR  r5, r2
        AND  r5, #1
        ADD  r5, #C_GRASS0
        LSL  r3, #4
        LEA  r6, [sn_unstubs + r3]
        LSL  r1, #3
        ADD  r1, [r6]+
        LSL  r2, #3
        ADD  r2, #GY
        ADD  r2, [r6]+
        MOV  r3, [r6]+
        MOV  r4, [r6]
        BRA  fill_rect

; head: the head facing r3, colour r5: a segment and two eyes
head:   SAVE r7-r11
        MOV  r8, r1
        MOV  r9, r2
        LSL  r3, #3
        LEA  r10, [sn_eyes + r3]        ; r10: the eyes' pixels
        BSR  block
        LSL  r8, #3
        LSL  r9, #3
        ADD  r9, #GY
        MOV  r11, #4                    ; white, pupil, white, pupil
.e:     MOV  r1, byte [r10]+
        ADD  r1, r8
        MOV  r2, byte [r10]+
        ADD  r2, r9
        MOV  r5, r11
        AND  r5, #1
        ADD  r5, #C_EYE
        BSR  pixel
        DBNZ r11, .e
        RESTORE r7-r11
        RET

; the food at (fx, fy): its image under its mask, two words a row. Leaf.
draw_food:
        MOV  r2, [r14 + S_FY]
        LSL  r2, #3
        ADD  r2, #GY
        MOV  r0, r2
        LSL  r0, #8
        LSL  r2, #6
        ADD  r2, r0
        ADD  r2, [sn_target]
        MOV  r1, [r14 + S_FX]
        LSL  r1, #3
        ADD  r2, r1
        LEA  r3, [sn_food_img]
        LEA  r4, [sn_food_mask]
        MOV  r5, #8
.r:     MOV  r0, [r4]+
        MOV  r1, [r2]
        MOV  r6, [r3]+
        MERGE r1, r6, r0
        MOV  [r2]+, r1
        MOV  r0, [r4]+
        MOV  r1, [r2]
        MOV  r6, [r3]+
        MERGE r1, r6, r0
        MOV  [r2], r1
        ADD  r2, #PITCH - 4
        DBNZ r5, .r
        RET

; a wall's cell: bricks 8 x 4, the joints staggered, as the C game's pattern
wall_cell:
        SAVE r7-r9
        LSL  r1, #3
        MOV  r8, r1             ; r8, r9: the cell's top left
        LSL  r2, #3
        ADD  r2, #GY
        MOV  r9, r2
        MOV  r3, #8
        MOV  r4, #8
        MOV  r5, #C_WALL
        BSR  fill_rect
        MOV  r1, r8
        MOV  r2, r9
        MOV  r3, #8
        MOV  r4, #1
        MOV  r5, #C_WALL_HI
        BSR  fill_rect
        MOV  r1, r8
        MOV  r2, r9
        ADD  r2, #4
        MOV  r3, #8
        MOV  r4, #1
        MOV  r5, #C_WALL_HI
        BSR  fill_rect
        MOV  r1, r8
        MOV  r2, r9
        INC  r2
        MOV  r3, #1
        MOV  r4, #3
        MOV  r5, #C_WALL_HI
        BSR  fill_rect
        MOV  r1, r8
        ADD  r1, #4
        MOV  r2, r9
        ADD  r2, #5
        MOV  r3, #1
        MOV  r4, #3
        MOV  r5, #C_WALL_HI
        BSR  fill_rect
        RESTORE r7-r9
        RET

draw_walls:
        SAVE r7-r8
        MOV  r8, #0
.tb:    MOV  r1, r8
        MOV  r2, #0
        BSR  wall_cell
        MOV  r1, r8
        MOV  r2, #GH - 1
        BSR  wall_cell
        INC  r8
        CMP  r8, #GW
        BNE  .tb
        MOV  r8, #1
.lr:    MOV  r1, #0
        MOV  r2, r8
        BSR  wall_cell
        MOV  r1, #GW - 1
        MOV  r2, r8
        BSR  wall_cell
        INC  r8
        CMP  r8, #GH - 1
        BNE  .lr
        RESTORE r7-r8
        RET

draw_grass:
        SAVE r7-r9
        MOV  r9, #1
.y:     MOV  r8, #1
.x:     MOV  r1, r8
        MOV  r2, r9
        BSR  grass
        INC  r8
        CMP  r8, #GW - 1
        BNE  .x
        INC  r9
        CMP  r9, #GH - 1
        BNE  .y
        RESTORE r7-r9
        RET

; dir_next: r1 a ring index; r3 the direction from its cell to the next
; one's. Leaf, r0-r4.
dir_next:
        MOV  r2, r1
        INC  r2
        AND  r2, #RING - 1
        MOV  r3, byte [sn_sx + r2]
        MOV  r0, byte [sn_sx + r1]
        CMP  r3, r0
        BHI  .r
        BLO  .l
        MOV  r3, byte [sn_sy + r2]
        MOV  r0, byte [sn_sy + r1]
        CMP  r3, r0
        BHI  .d
        MOV  r3, #3
        RET
.r:     MOV  r3, #0
        RET
.d:     MOV  r3, #1
        RET
.l:     MOV  r3, #2
        RET

; every segment, the head: what a full redraw draws over the empty board
draw_snake:
        SAVE r7-r9
        MOV  r8, [r14 + S_TAIL]
.s:     CMP  r8, [r14 + S_HEAD]
        BEQ  .h
        MOV  r9, r8
        AND  r9, #15
        ADD  r9, #C_BODY        ; r9: the segment's colour
        MOV  r1, byte [sn_sx + r8]
        MOV  r2, byte [sn_sy + r8]
        MOV  r5, r9
        BSR  block
        MOV  r1, r8
        BSR  dir_next
        MOV  r1, byte [sn_sx + r8]
        MOV  r2, byte [sn_sy + r8]
        MOV  r5, r9
        BSR  bridge
        INC  r8
        AND  r8, #RING - 1
        BRA  .s
.h:     MOV  r1, byte [sn_sx + r8]
        MOV  r2, byte [sn_sy + r8]
        MOV  r3, [r14 + S_DIR]
        MOV  r5, #C_HEAD
        BSR  head
        RESTORE r7-r9
        RET

; the bar: its labels once, the numbers when they change
draw_bar_labels:
        SAVE r7
        MOV  r1, #0
        MOV  r2, #0
        MOV  r3, #320
        MOV  r4, #GY
        MOV  r5, #C_BAR
        BSR  fill_rect
        MOV  r1, #0
        MOV  r2, #GY - 2
        MOV  r3, #320
        MOV  r4, #1
        MOV  r5, #C_BAR_LINE
        BSR  fill_rect
        MOV  r1, #8
        LEA  r3, [s_score]
        MOV  r4, #C_BAR_TEXT
        BSR  bar_text
        MOV  r1, #112
        LEA  r3, [s_len]
        MOV  r4, #C_BAR_TEXT
        BSR  bar_text
        MOV  r1, #232
        LEA  r3, [s_best]
        MOV  r4, #C_BAR_DIM
        BSR  bar_text
        RESTORE r7
        RET

; bar_text: r1 x, r3 the string, r4 fg, on the bar
bar_text:
        MOV  r2, #4
        MOV  r5, #C_BAR
        BRA  text

draw_numbers:
        SAVE r7
        MOV  r1, [r14 + S_SCORE]
        LEA  r2, [sn_buf + 5]
        MOV  r3, #5
        MOV  r4, #0
        BSR  digits
        MOV  r3, r2
        MOV  r1, #56
        MOV  r4, #C_BAR_TEXT
        BSR  bar_text
        MOV  r1, [r14 + S_HEAD]
        SUB  r1, [r14 + S_TAIL]
        AND  r1, #RING - 1
        LEA  r2, [sn_buf + 3]
        MOV  r3, #3
        MOV  r4, #1
        BSR  digits
        MOV  r3, r2
        MOV  r1, #144
        MOV  r4, #C_BAR_TEXT
        BSR  bar_text
        MOV  r1, [r14 + S_BEST]
        LEA  r2, [sn_buf + 5]
        MOV  r3, #5
        MOV  r4, #0
        BSR  digits
        MOV  r3, r2
        MOV  r1, #272
        MOV  r4, #C_BAR_DIM
        BSR  bar_text
        RESTORE r7
        RET

; ---- big fills and copies: a store loop, or FILL and COPY (blk) ----

; big_fill: r1 the first word, r2 the value, r3 words (> 0). Leaf.
big_fill:
        MOVS r0, [_snake_blk]
        BNE  .blk
        MOV  r4, r3
        LSR  r4, #3
        BEQ  .one
.w8:    MOV  [r1]+, r2
        MOV  [r1]+, r2
        MOV  [r1]+, r2
        MOV  [r1]+, r2
        MOV  [r1]+, r2
        MOV  [r1]+, r2
        MOV  [r1]+, r2
        MOV  [r1]+, r2
        DBNZ r4, .w8
.one:   AND  r3, #7
        BEQ  .x
.w1:    MOV  [r1]+, r2
        DBNZ r3, .w1
.x:     RET
.blk:   MOV  r4, r3
.chunk: MOV  r3, r4
        CMP  r3, #256
        BLS  .f
        MOV  r3, #256
.f:     MOV  r0, #-1            ; the condition latch cleared (gfx/blk/blk.s)
        CLZ  r0, r0
        .half 0x01FD            ; FILL: r3 words of r2 from r1
        SUB  r4, r3
        BNE  .chunk
        RET

; big_copy: r1 to, r2 from, r3 words (> 0). Leaf.
big_copy:
        MOVS r0, [_snake_blk]
        BNE  .blk
        MOV  r4, r3
        LSR  r4, #2
        BEQ  .one
.w4:    MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r4, .w4
.one:   AND  r3, #3
        BEQ  .x
.w1:    MOV  r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r3, .w1
.x:     RET
.blk:   MOV  r4, r3
.chunk: MOV  r3, r4
        CMP  r3, #256
        BLS  .c
        MOV  r3, #256
.c:     MOV  r0, #-1
        CLZ  r0, r0
        .half 0x02FD            ; COPY: r3 words from r2 to r1
        SUB  r4, r3
        BNE  .chunk
        RET

; fill_screen: rows r1..r1 + r2 of the target in colour r3, whole rows
fill_rows:
        MOV  r0, r1
        LSL  r0, #8
        LSL  r1, #6
        ADD  r1, r0
        ADD  r1, [sn_target]
        MOV  r0, r2
        LSL  r0, #6
        LSL  r2, #4
        ADD  r2, r0             ; r2: 80 words a row
        MOV  r0, r2
        MOV  r2, [sn_solid + r3*4]
        MOV  r3, r0
        BRA  big_fill

; ======================================================================
; the palette and the descriptors
; ======================================================================

set_palette:
        LEA  r1, [sn_pal]
        MOV  r4, #VID_PAL
.e:     MOV  r2, half [r1]
        MOV  r3, half [r1 + 2]
        ADD  r1, #4
        TST  r2, r2
        BEQ  .body
        MOV  [r4 + r2*4], r3
        BRA  .e
.body:  LEA  r1, [sn_body]
        MOV  r2, #VID_PAL + 4 * C_BODY
        MOV  r3, #16
.b:     MOV  r0, [r1]+
        MOV  [r2]+, r0
        DBNZ r3, .b
        RET

; each frame: the body's 16 colours a step on, the food's glint, the
; blinking text, the grass's flash. Leaf.
palette_frame:
        MOV  r1, [r14 + S_FRAME]
        LSR  r1, #1
        NEG  r1, r1             ; entry k gets body[(k - frame / 2) & 15]
        LEA  r3, [sn_body]
        MOV  r2, #VID_PAL + 4 * C_BODY
        MOV  r4, #16
.b:     MOV  r0, r1
        AND  r0, #15
        MOV  r0, [r3 + r0*4]
        MOV  [r2]+, r0
        INC  r1
        DBNZ r4, .b
        MOV  r1, [r14 + S_FRAME]
        MOV  r0, r1
        AND  r0, #31
        CMP  r0, #16
        BLO  .g
        XOR  r0, #31
.g:     MOV  r0, [sn_glint + r0*4]
        MOV  [VID_PAL + 4 * C_FOOD_HI], r0
        MOV  r0, #0xFFFF
        TST  r1, #32
        BNE  .bl
        MOV  r0, #0x3A27
.bl:    MOV  [VID_PAL + 4 * C_BLINK], r0
        MOVS r0, [sn_flash]
        BEQ  .x
        DEC  r0
        MOV  [sn_flash], r0
        BEQ  .off
        MOV  r0, #0x3366
        MOV  [VID_PAL + 4 * C_GRASS0], r0
        MOV  r0, #0x3BE7
        MOV  [VID_PAL + 4 * C_GRASS1], r0
.x:     RET
.off:   MOV  r0, #0x1223
        MOV  [VID_PAL + 4 * C_GRASS0], r0
        MOV  r0, #0x1A84
        MOV  [VID_PAL + 4 * C_GRASS1], r0
        RET

; map_rows: r1 the first screen row, r2 its descriptor, r3 rows: each row
; on two lines, the next row 80 words on. Leaf.
map_rows:
        MOV  r0, #TABLE0
        LSL  r1, #3
        ADD  r0, r1
.r:     MOV  [r0]+, r2
        MOV  [r0]+, r2
        ADD  r2, #80
        DBNZ r3, .r
        RET

show_screen:
        MOV  r1, #0
        MOV  r2, #FB_DESC
        MOV  r3, #240
        BRA  map_rows

; show_banner: r1 a banner's row 0's descriptor over the screen's middle,
; or 0 for the screen again
show_banner:
        MOV  r2, #FB_DESC + BANNER_Y * 80
        TST  r1, r1
        BEQ  .s
        MOV  r2, r1
.s:     MOV  r1, #BANNER_Y
        MOV  r3, #BANNER_H
        BRA  map_rows

; shake: the picture moved down r1 rows (up if negative), the edges
; repeated. Leaf.
shake:  MOV  r0, #TABLE0
        MOV  r2, #0             ; r2: the screen's row
        MOV  r3, #240
.r:     MOV  r4, r2
        SUB  r4, r1
        BPL  .lo
        MOV  r4, #0
.lo:    CMP  r4, #239
        BLE  .hi
        MOV  r4, #239
.hi:    MOV  r5, r4
        LSL  r5, #6
        LSL  r4, #4
        ADD  r4, r5
        ADD  r4, #FB_DESC
        MOV  [r0]+, r4
        MOV  [r0]+, r4
        INC  r2
        DEC  r3
        BNE  .r
        RET

; ripple: the title's rows 32-103 rippling, each line a row up to 2
; above or below its own by a sine running down the band. Leaf.
ripple: MOV  r0, #TABLE0 + 64 * 4
        MOV  r1, [r14 + S_FRAME]
        MOV  r2, r1
        ADD  r1, r1
        ADD  r1, r2             ; r1: 3 * frame, the sine's phase
        MOV  r2, #FB_DESC + 32 * 80
        LEA  r3, [sn_ripple]
        MOV  r4, #72
.l:     MOV  r5, r1
        AND  r5, #63
        MOV  r5, [r3 + r5*4]
        ADD  r5, r2
        MOV  [r0]+, r5
        ADD  r1, #2
        MOV  r5, r1
        AND  r5, #63
        MOV  r5, [r3 + r5*4]
        ADD  r5, r2
        MOV  [r0]+, r5
        ADD  r1, #2
        ADD  r2, #80
        DEC  r4
        BNE  .l
        RET

; ======================================================================
; the game
; ======================================================================

rnd:    MOV  r1, [sn_seed]
        MOV  r0, #1103515245
        MULU r0:r1, r0
        ADD  r1, #12345
        MOV  [sn_seed], r1
        LSR  r1, #16
        RET

; place_food: a free cell, drawn
place_food:
        SAVE r7-r8
.again: BSR  rnd
        MOV  r0, #GW - 2
        DIVU r0:r1, r0
        INC  r0
        MOV  r8, r0             ; r8: x
        BSR  rnd
        MOV  r0, #GH - 2
        DIVU r0:r1, r0
        INC  r0                 ; r0: y
        MOV  r1, r0
        LSL  r1, #6
        ADD  r1, r8
        MOVS r2, byte [sn_grid + r1]
        BNE  .again
        MOV  r2, #G_FOOD
        MOV  byte [sn_grid + r1], r2
        MOV  [r14 + S_FX], r8
        MOV  [r14 + S_FY], r0
        BSR  draw_food
        RESTORE r7-r8
        RET

new_game:
        SAVE r7-r8
        ; the grid: free, walls round it
        LEA  r1, [sn_grid]
        MOV  r2, #0
        MOV  r3, #GH * 64 / 4
        BSR  big_fill
        MOV  r0, #G_WALL
        MOV  r1, #0
.tb:    MOV  byte [sn_grid + r1], r0
        MOV  byte [sn_grid + (GH - 1) * 64 + r1], r0
        INC  r1
        CMP  r1, #GW
        BNE  .tb
        MOV  r1, #0
.lr:    MOV  byte [sn_grid + r1], r0
        MOV  byte [sn_grid + GW - 1 + r1], r0
        ADD  r1, #64
        CMP  r1, #GH * 64
        BNE  .lr
        BSR  draw_bar_labels
        BSR  draw_walls
        BSR  draw_grass
        ; four cells in the middle row, heading right
        MOV  r1, #0
        MOV  r0, #G_SNAKE
.s:     MOV  r2, r1
        ADD  r2, #6
        MOV  byte [sn_sx + r1], r2
        MOV  r3, #GH / 2
        MOV  byte [sn_sy + r1], r3
        ADD  r2, #GH / 2 * 64
        MOV  byte [sn_grid + r2], r0
        INC  r1
        CMP  r1, #4
        BNE  .s
        MOV  r0, #0
        MOV  [r14 + S_TAIL], r0
        MOV  [r14 + S_DIR], r0
        MOV  [r14 + S_GROW], r0
        MOV  [r14 + S_SCORE], r0
        MOV  [r14 + S_FOODS], r0
        MOV  [r14 + S_STEPS], r0
        MOV  [r14 + S_PAUSED], r0
        MOV  [r14 + S_TICK], r0
        MOV  [sn_nturns], r0
        MOV  r0, #3
        MOV  [r14 + S_HEAD], r0
        MOV  r0, #5
        MOV  [r14 + S_PERIOD], r0
        MOV  r0, #1
        MOV  [r14 + S_ALIVE], r0
        BSR  draw_snake
        BSR  place_food
        BSR  draw_numbers
        RESTORE r7-r8
        RET

; room: r1 x, r2 y, r3 a limit: how many cells are reachable from (x, y)
; through free cells and the food, up to the limit (breadth first, the
; cells marked with a new stamp, the queue of cell indices y * 64 + x).
; Leaf; saves r8-r13.
room:   SAVE r8-r13
        LEA  r8, [sn_seen]      ; r8: the stamps, a half a cell
        LEA  r9, [sn_grid]      ; r9: the grid
        MOV  r4, [sn_stamp]
        INC  r4
        MOV  [sn_stamp], r4     ; r4: this search's stamp
        LEA  r10, [sn_queue]    ; r10: the queue's head
        MOV  r11, r10           ; r11: its tail
        LSL  r2, #6
        ADD  r2, r1
        MOV  half [r8 + r2*2], r4
        MOV  half [r11], r2
        ADD  r11, #2
        MOV  r12, #0            ; r12: the cells counted
        LEA  r13, [sn_queue + 256]
.next:  CMP  r10, r11
        BHS  .done
        CMP  r12, r3
        BHS  .done
        MOV  r5, half [r10]
        ADD  r10, #2
        INC  r12
        LEA  r1, [sn_nbr]
        MOV  r2, #4
.nb:    MOV  r6, r5
        ADD  r6, [r1]+          ; a neighbour
        MOVS r0, byte [r9 + r6]
        BEQ  .free
        CMP  r0, #G_FOOD
        BNE  .skip
.free:  MOV  r0, half [r8 + r6*2]
        CMP  r0, r4
        BEQ  .skip
        CMP  r11, r13
        BHS  .skip
        MOV  half [r8 + r6*2], r4
        MOV  half [r11], r6
        ADD  r11, #2
.skip:  DEC  r2
        BNE  .nb
        BRA  .next
.done:  MOV  r1, r12
        RESTORE r8-r13
        RET

; think: the autopilot's direction, in r1: of straight on, right and left,
; the open one nearest the food, one that leaves less room than the
; snake's length (up to 100) counting 1000 more
think:  SAVE r7-r13
        MOV  r13, [r14 + S_HEAD]
        SUB  r13, [r14 + S_TAIL]
        AND  r13, #RING - 1
        CMP  r13, #100
        BLS  .w
        MOV  r13, #100          ; r13: the room wanted
.w:     MOV  r8, [r14 + S_DIR]  ; r8: the best direction
        MOV  r9, #0x7FFFFFFF    ; r9: its score
        MOV  r10, #0            ; r10: the choice, 0-2
.k:     MOV  r11, [sn_turnoff + r10*4]
        ADD  r11, [r14 + S_DIR]
        AND  r11, #3            ; r11: the direction
        MOV  r0, [r14 + S_HEAD]
        MOV  r1, byte [sn_sx + r0]
        ADD  r1, [sn_dx + r11*4]
        MOV  r2, byte [sn_sy + r0]
        ADD  r2, [sn_dy + r11*4]
        MOV  r3, r2
        LSL  r3, #6
        ADD  r3, r1
        MOVS r0, byte [sn_grid + r3]
        BEQ  .open
        CMP  r0, #G_FOOD
        BEQ  .open
        CMP  r0, #G_WALL
        BEQ  .no
        ; the snake: only its tail, if it moves away
        MOVS r0, [r14 + S_GROW]
        BNE  .no
        MOV  r0, [r14 + S_TAIL]
        MOV  r3, byte [sn_sx + r0]
        CMP  r3, r1
        BNE  .no
        MOV  r3, byte [sn_sy + r0]
        CMP  r3, r2
        BNE  .no
.open:  MOV  r12, r1            ; r12: the distance to the food
        SUB  r12, [r14 + S_FX]
        BPL  .ax
        NEG  r12, r12
.ax:    MOV  r0, r2
        SUB  r0, [r14 + S_FY]
        BPL  .ay
        NEG  r0, r0
.ay:    ADD  r12, r0
        MOV  r3, r13
        BSR  room
        CMP  r1, r13
        BHS  .roomy
        ADD  r12, #1000
.roomy: CMP  r12, r9
        BGE  .no
        MOV  r9, r12
        MOV  r8, r11
.no:    INC  r10
        CMP  r10, #3
        BNE  .k
        MOV  r1, r8
        RESTORE r7-r13
        RET

; step: a turn typed ahead (not back on itself), the autopilot, the move:
; the tail's cell erased, the old head turned into body, the new head
step:   SAVE r7-r13
        MOVS r0, [sn_nturns]
        BEQ  .auto
        DEC  r0
        MOV  [sn_nturns], r0
        MOV  r1, [sn_turns]
        MOV  r0, [sn_turns + 4]
        MOV  [sn_turns], r0
        MOV  r0, [sn_turns + 8]
        MOV  [sn_turns + 4], r0
        MOV  r0, [sn_turns + 12]
        MOV  [sn_turns + 8], r0
        MOV  r0, [r14 + S_DIR]
        XOR  r0, #2             ; the way back
        CMP  r1, r0
        BEQ  .auto
        MOV  [r14 + S_DIR], r1
.auto:  MOVS r0, [r14 + S_AUTO]
        BEQ  .move
        BSR  think
        MOV  [r14 + S_DIR], r1
.move:  CALL _video_ticks
        MOV  r13, r1            ; r13: the step's drawing starts
        MOV  r0, [r14 + S_HEAD]
        MOV  r11, [r14 + S_DIR]
        MOV  r8, byte [sn_sx + r0]
        ADD  r8, [sn_dx + r11*4]        ; r8, r9: the new head
        MOV  r9, byte [sn_sy + r0]
        ADD  r9, [sn_dy + r11*4]
        MOVS r0, [r14 + S_GROW]
        BEQ  .tail
        DEC  r0
        MOV  [r14 + S_GROW], r0
        BRA  .check
        ; the tail goes: its cell's grass, its bridge's half in the next cell
.tail:  MOV  r10, [r14 + S_TAIL]
        MOV  r1, byte [sn_sx + r10]
        MOV  r2, byte [sn_sy + r10]
        BSR  grass
        MOV  r1, r10
        BSR  dir_next
        MOV  r1, byte [sn_sx + r10]
        MOV  r2, byte [sn_sy + r10]
        BSR  unstub
        MOV  r1, byte [sn_sy + r10]
        LSL  r1, #6
        MOV  r0, byte [sn_sx + r10]
        ADD  r1, r0
        MOV  r0, #G_FREE
        MOV  byte [sn_grid + r1], r0
        INC  r10
        AND  r10, #RING - 1
        MOV  [r14 + S_TAIL], r10
.check: MOV  r12, r9
        LSL  r12, #6
        ADD  r12, r8
        MOVS r12, byte [sn_grid + r12]  ; r12: what's there
        CMP  r12, #G_WALL
        BEQ  .dead
        CMP  r12, #G_SNAKE
        BNE  .go
.dead:  MOV  r0, [r14 + S_HEAD]
        MOV  r1, byte [sn_sx + r0]
        MOV  r2, byte [sn_sy + r0]
        MOV  r3, r11
        MOV  r5, #C_DEAD
        BSR  head
        MOV  r0, #0
        MOV  [r14 + S_ALIVE], r0
        RESTORE r7-r13
        RET
.go:    MOV  r10, [r14 + S_HEAD]        ; r10: the old head
        MOV  r0, r10
        INC  r0
        AND  r0, #RING - 1
        MOV  [r14 + S_HEAD], r0
        MOV  byte [sn_sx + r0], r8
        MOV  byte [sn_sy + r0], r9
        MOV  r1, r9
        LSL  r1, #6
        ADD  r1, r8
        MOV  r0, #G_SNAKE
        MOV  byte [sn_grid + r1], r0
        ; the old head is body now
        MOV  r1, byte [sn_sx + r10]
        MOV  r2, byte [sn_sy + r10]
        MOV  r5, r10
        AND  r5, #15
        ADD  r5, #C_BODY
        BSR  block
        MOV  r1, byte [sn_sx + r10]
        MOV  r2, byte [sn_sy + r10]
        MOV  r3, r11
        MOV  r5, r10
        AND  r5, #15
        ADD  r5, #C_BODY
        BSR  bridge
        MOV  r1, r8
        MOV  r2, r9
        MOV  r3, r11
        MOV  r5, #C_HEAD
        BSR  head
        ; the step's drawing, measured
        CALL _video_ticks
        SUB  r1, r13
        MOV  r0, [sn_step_sum]
        ADD  r0, r1
        MOV  [sn_step_sum], r0
        INC  [sn_step_n]
        CMP  r1, [sn_step_max]
        BLS  .m
        MOV  [sn_step_max], r1
.m:     INC  [r14 + S_STEPS]
        CMP  r12, #G_FOOD
        BNE  .x
        ; eaten: the score, three more cells, faster every third, new food
        MOV  r0, [r14 + S_SCORE]
        ADD  r0, #10
        MOV  [r14 + S_SCORE], r0
        CMP  r0, [r14 + S_BEST]
        BLS  .b
        MOV  [r14 + S_BEST], r0
.b:     MOV  r0, [r14 + S_GROW]
        ADD  r0, #3
        MOV  [r14 + S_GROW], r0
        MOV  r1, [r14 + S_FOODS]
        INC  r1
        MOV  [r14 + S_FOODS], r1
        MOV  r0, #3
        DIVU r0:r1, r0
        TST  r0, r0
        BNE  .f
        MOV  r0, [r14 + S_PERIOD]
        CMP  r0, #2
        BLS  .f
        DEC  r0
        MOV  [r14 + S_PERIOD], r0
.f:     BSR  place_food
        BSR  draw_numbers
        MOV  r0, #6
        MOV  [sn_flash], r0
.x:     RESTORE r7-r13
        RET

; input: the events; arrows queue turns, a the autopilot, p the pause
input:  SAVE r7-r8
.ev:    LEA  r1, [sn_event]
        CALL _input_next
        TST  r1, r1
        BEQ  .done
        MOV  r0, [sn_event]
        CMP  r0, #EV_KEY
        BNE  .ev
        MOV  r8, [sn_event + 4]         ; the key
        MOV  r0, r8
        SUB  r0, #K_UP
        CMP  r0, #3
        BHI  .other
        MOV  r0, [sn_keydir + r0*4]     ; up, down, left, right: 3, 1, 2, 0
        MOV  r1, [sn_nturns]
        CMP  r1, #4
        BHS  .ev
        LSL  r1, #2
        MOV  [sn_turns + r1], r0
        INC  [sn_nturns]
        BRA  .ev
.other: CMP  r8, #'a'
        BNE  .p
        MOV  r0, [r14 + S_AUTO]
        XOR  r0, #1
        MOV  [r14 + S_AUTO], r0
        BRA  .ev
.p:     CMP  r8, #'p'
        BNE  .esc
        MOV  r0, [r14 + S_PAUSED]
        XOR  r0, #1
        MOV  [r14 + S_PAUSED], r0
        MOV  r1, #0
        TST  r0, r0
        BEQ  .pb
        MOV  r1, #PBANNER_DESC
.pb:    BSR  show_banner
        BRA  .ev
.esc:   CMP  r8, #K_ESC
        BNE  .ev
        MOV  r0, #0
        MOV  [r14 + S_ALIVE], r0
        BRA  .ev
.done:  RESTORE r7-r8
        RET

; draw_banner: r1 the big words, r2 the small line (centred, cell font),
; r3 the banner's buffer
draw_banner:
        SAVE r7-r9
        MOV  r8, r1
        MOV  r9, r2
        MOV  [sn_target], r3
        MOV  r1, #0
        MOV  r2, #BANNER_H
        MOV  r3, #C_BANNER
        BSR  fill_rows
        MOV  r1, #0
        MOV  r2, #1
        MOV  r3, #320
        MOV  r4, #1
        MOV  r5, #C_BANNER_HI
        BSR  fill_rect
        MOV  r1, #0
        MOV  r2, #BANNER_H - 2
        MOV  r3, #320
        MOV  r4, #1
        MOV  r5, #C_BANNER_HI
        BSR  fill_rect
        ; the big words: 6 dots of 4 a letter, less one
        MOV  r1, r8
        BSR  strlen
        MOV  r0, r1
        LSL  r1, #1
        ADD  r1, r0
        LSL  r1, #3
        SUB  r1, #4             ; 24n - 4 pixels
        MOV  r0, #320
        SUB  r0, r1
        LSR  r0, #1
        AND  r0, #-4
        MOV  r1, r0
        MOV  r2, #3
        MOV  r3, r8
        MOV  r4, #4
        MOV  r5, #C_BANNER_TX
        BSR  block_text
        ; the small line
        MOV  r1, r9
        BSR  strlen
        LSL  r1, #3
        MOV  r0, #320
        SUB  r0, r1
        LSR  r0, #1
        AND  r0, #-4
        MOV  r1, r0
        MOV  r2, #BANNER_H - 18
        MOV  r3, r9
        MOV  r4, #C_BANNER_HI
        MOV  r5, #C_BANNER
        BSR  text
        LEA  r0, [FB]
        MOV  [sn_target], r0
        RESTORE r7-r9
        RET

; strlen: r1 the string; r1 its length. Leaf.
strlen: MOV  r2, r1
.l:     MOVS r0, byte [r2]+
        BNE  .l
        SUB  r2, r1
        DEC  r2
        MOV  r1, r2
        RET

; the title, until space
title:  SAVE r7-r9
        CALL _video_ticks
        MOV  r9, r1
        MOV  r1, #0
        MOV  r2, #240
        MOV  r3, #C_TITLE_BG
        BSR  fill_rows
        MOV  r1, #44            ; "SNAKE": 29 dots of 8, centred
        MOV  r2, #40
        LEA  r3, [s_snake]
        MOV  r4, #8
        MOV  r5, #-1
        BSR  block_text
        MOV  r1, #44
        MOV  r2, #112
        MOV  r3, #232
        MOV  r4, #2
        MOV  r5, #C_BAR_LINE
        BSR  fill_rect
        MOV  r1, #80
        MOV  r2, #132
        LEA  r3, [s_press]
        MOV  r4, #C_BLINK
        MOV  r5, #C_TITLE_BG
        BSR  text
        MOV  r1, #24
        MOV  r2, #176
        LEA  r3, [s_keys]
        MOV  r4, #C_BAR_DIM
        MOV  r5, #C_TITLE_BG
        BSR  text
        CALL _video_ticks
        SUB  r1, r9
        MOV  r2, r1
        LEA  r1, [s_title_draw]
        CALL _perf_value
        BSR  show_screen
        MOV  r8, #0
.f:     CALL _video_wait
        BSR  set_frame
        BSR  palette_frame
        BSR  ripple
        INC  r8
        CMP  r8, #40
        BNE  .k
        LEA  r1, [s_title]
        CALL _rt_shot
.k:     LEA  r1, [sn_event]
        CALL _input_next
        TST  r1, r1
        BEQ  .f
        MOV  r0, [sn_event]
        CMP  r0, #EV_KEY
        BNE  .k
        MOV  r0, [sn_event + 4]
        CMP  r0, #' '
        BNE  .k
        MOV  r0, [_rt_frames]
        MOV  [sn_t_space], r0
        RESTORE r7-r9
        RET

; set_frame: the frame count for the colours: the runtime's, so they
; keep time however long drawing takes. Leaf.
set_frame:
        MOV  r0, [_rt_frames]
        MOV  [r14 + S_FRAME], r0
        RET

play:   SAVE r7-r9
        BSR  new_game
        ; ready: the board under a banner until 45 frames after the start
        LEA  r1, [s_ready]
        LEA  r2, [s_steer]
        MOV  r3, #BANNER
        BSR  draw_banner
        BSR  show_screen
        MOV  r1, #BANNER_DESC
        BSR  show_banner
.ready: MOV  r0, [_rt_frames]
        MOV  r1, [sn_t_space]
        ADD  r1, #45
        CMP  r0, r1
        BHS  .go
        CALL _video_wait
        BSR  set_frame
        BSR  palette_frame
        BRA  .ready
.go:    MOV  r1, #0
        BSR  show_banner
        MOV  r9, #0             ; the shot taken
.frame: MOVS r0, [r14 + S_ALIVE]
        BEQ  .over
        CALL _video_wait        ; the frames since the last: steps keep time
        ADD  r1, [r14 + S_TICK]
        MOV  [r14 + S_TICK], r1
        CALL _perf_frame_begin
        BSR  set_frame
        BSR  palette_frame
        BSR  input
        MOVS r0, [r14 + S_PAUSED]
        BEQ  .run
        MOV  r0, #0
        MOV  [r14 + S_TICK], r0
        BRA  .end
.run:   MOVS r0, [r14 + S_ALIVE]
        BEQ  .end
        MOV  r0, [r14 + S_TICK]
        CMP  r0, [r14 + S_PERIOD]
        BLO  .end
        MOV  r0, #0
        MOV  [r14 + S_TICK], r0
        BSR  step
.end:   CALL _perf_frame_end
        TST  r9, r9
        BNE  .frame
        MOV  r0, [r14 + S_STEPS]
        CMP  r0, #200
        BNE  .frame
        MOV  r9, #1
        LEA  r1, [s_game]
        CALL _rt_shot
        BRA  .frame
.over:  LEA  r1, [s_game_frame]
        CALL _perf_frames
        MOV  r1, [sn_step_sum]
        MOV  r0, [sn_step_n]
        DIVU r0:r1, r0
        MOV  r2, r1
        LEA  r1, [s_step_avg]
        CALL _perf_value
        LEA  r1, [s_step_max]
        MOV  r2, [sn_step_max]
        CALL _perf_value
        RESTORE r7-r9
        RET

game_over:
        SAVE r7-r9
        ; "SCORE n" for the banner's small line
        MOV  r1, [r14 + S_SCORE]
        LEA  r2, [sn_buf + 16]
        MOV  r3, #5
        MOV  r4, #1
        BSR  digits
.sp:    MOVS r0, byte [r2]      ; past the spaces
        CMP  r0, #' '
        BNE  .ns
        INC  r2
        BRA  .sp
.ns:    LEA  r1, [sn_line]
        LEA  r3, [s_score_]
.cs:    MOVS r0, byte [r3]+
        MOV  byte [r1], r0
        INC  r1
        TST  r0, r0
        BNE  .cs
        DEC  r1
.cn:    MOVS r0, byte [r2]+
        MOV  byte [r1], r0
        INC  r1
        TST  r0, r0
        BNE  .cn
        LEA  r1, [s_gameover]
        LEA  r2, [sn_line]
        MOV  r3, #BANNER
        BSR  draw_banner
        ; the crash: the picture shaken by its descriptors
        MOV  r8, #0
.sh:    CALL _video_wait
        BSR  set_frame
        BSR  palette_frame
        MOV  r1, r8
        MOV  r0, #6
        DIVU r0:r1, r0
        SUB  r1, #3             ; k / 6 - 3, negated on odd frames
        TST  r8, #1
        BEQ  .e
        NEG  r1, r1
.e:     BSR  shake
        INC  r8
        CMP  r8, #16
        BNE  .sh
        BSR  show_screen
        MOV  r1, #BANNER_DESC
        BSR  show_banner
        MOV  r8, #0
.w:     CALL _video_wait
        BSR  set_frame
        BSR  palette_frame
        INC  r8
        CMP  r8, #20
        BNE  .w2
        LEA  r1, [s_game_over]
        CALL _rt_shot
.w2:    CMP  r8, #40
        BNE  .w
        RESTORE r7-r9
        RET

; ======================================================================
; the measurements: the same as the C game's, where they compare
; ======================================================================

tic:    PUSH r7
        CALL _video_ticks
        MOV  [sn_t0], r1
        POP  r7
        RET

; toc: r1 the name, r2 the repetitions: the ticks since tic, each
toc:    SAVE r7-r9
        MOV  r8, r1
        MOV  r9, r2
        CALL _video_ticks
        SUB  r1, [sn_t0]
        DIVU r0:r1, r9
        MOV  r2, r1
        MOV  r1, r8
        CALL _perf_value
        RESTORE r7-r9
        RET

step_cells:
        PUSH r7
        MOV  r1, #19
        MOV  r2, #12
        BSR  grass
        MOV  r1, #19
        MOV  r2, #12
        MOV  r3, #0
        BSR  unstub
        MOV  r1, #20
        MOV  r2, #12
        MOV  r5, #C_BODY
        BSR  block
        MOV  r1, #20
        MOV  r2, #12
        MOV  r3, #0
        MOV  r5, #C_BODY
        BSR  bridge
        MOV  r1, #21
        MOV  r2, #12
        MOV  r3, #0
        MOV  r5, #C_HEAD
        BSR  head
        POP  r7
        RET

measure:
        SAVE r7-r8
        BSR  show_screen
        ; the empty board, kept for redrawing from
        LEA  r0, [BG]
        MOV  [sn_target], r0
        BSR  tic
        BSR  draw_walls
        BSR  draw_grass
        LEA  r1, [s_board]
        MOV  r2, #1
        BSR  toc
        LEA  r0, [FB]
        MOV  [sn_target], r0
        ; a cell, a hundred times
        BSR  tic
        MOV  r8, #100
.c:     MOV  r1, #160
        MOV  r2, #120
        MOV  r3, #8
        MOV  r4, #8
        MOV  r5, #C_GRASS0
        BSR  fill_rect
        DBNZ r8, .c
        LEA  r1, [s_fill_cell]
        MOV  r2, #100
        BSR  toc
        BSR  tic
        MOV  r8, #10
.sc:    BSR  step_cells
        DBNZ r8, .sc
        LEA  r1, [s_step_cells]
        MOV  r2, #10
        BSR  toc
        ; the playfield: filled, copied from the empty board, redrawn
        BSR  tic
        MOV  r1, #GY
        MOV  r2, #240 - GY
        MOV  r3, #C_GRASS0
        BSR  fill_rows
        LEA  r1, [s_field_fill]
        MOV  r2, #1
        BSR  toc
        BSR  tic
        BSR  copy_field
        LEA  r1, [s_field_blit]
        MOV  r2, #1
        BSR  toc
        BSR  tic
        BSR  copy_field
        BSR  draw_snake
        BSR  draw_food
        LEA  r1, [s_full_redraw]
        MOV  r2, #1
        BSR  toc
        BSR  tic
        BSR  draw_snake
        LEA  r1, [s_snake_redraw]
        MOV  r2, #1
        BSR  toc
        BSR  tic
        MOV  r8, #10
.p:     BSR  palette_frame
        DBNZ r8, .p
        LEA  r1, [s_palette]
        MOV  r2, #10
        BSR  toc
        ; the bar's 13 digits
        BSR  tic
        MOV  r8, #10
.d:     BSR  draw_numbers
        DBNZ r8, .d
        LEA  r1, [s_digits]
        MOV  r2, #10
        BSR  toc
        BSR  tic
        MOV  r8, #10
.s:     BSR  show_screen
        DBNZ r8, .s
        LEA  r1, [s_desc]
        MOV  r2, #10
        BSR  toc
        BSR  tic
        MOV  r8, #10
.r:     BSR  ripple
        DBNZ r8, .r
        LEA  r1, [s_ripple]
        MOV  r2, #10
        BSR  toc
        BSR  show_screen
        RESTORE r7-r8
        RET

copy_field:
        MOV  r1, #FB + GY * PITCH
        MOV  r2, #BG + GY * PITCH
        MOV  r3, #(240 - GY) * 80
        BRA  big_copy

; ======================================================================
; data
; ======================================================================

        .data
        .align 4
; bit i of every pixel (L0, L1), and each pixel's bits
sn_planes0:
        .word 0x01010101, 0x02020202, 0x04040404, 0x08080808
        .word 0x10101010, 0x20202020, 0x40404040, 0x80808080
sn_planes1:
        .word 0x00000055, 0x00005500, 0x00550000, 0x55000000
        .word 0x000000AA, 0x0000AA00, 0x00AA0000, 0xAA000000
sn_pmask0:
        .word 0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000
sn_pmask1:
        .word 0x03030303, 0x0C0C0C0C, 0x30303030, 0xC0C0C0C0

; directions: right, down, left, up
sn_dx:  .word 1, 0, -1, 0
sn_dy:  .word 0, 1, 0, -1
sn_turnoff:
        .word 0, 1, 3           ; straight on, right, left
sn_keydir:
        .word 3, 1, 2, 0        ; K_UP, K_DOWN, K_LEFT, K_RIGHT
sn_nbr: .word 1, 64, -1, -64    ; a cell's neighbours in the grid
; the bridges (x, y, w, h in the cell), and the stubs they leave in the next cell
sn_bridges:
        .word 7, 1, 2, 6,  1, 7, 6, 2,  -1, 1, 2, 6,  1, -1, 6, 2
sn_unstubs:
        .word 0, 1, 1, 6,  1, 0, 6, 1,  7, 1, 1, 6,  1, 7, 6, 1
; the eyes by direction: white, pupil, white, pupil (x, y)
sn_eyes:
        .byte 5, 2, 6, 2, 5, 5, 6, 5,  2, 5, 2, 6, 5, 5, 5, 6
        .byte 2, 2, 1, 2, 2, 5, 1, 5,  2, 2, 2, 1, 5, 2, 5, 1
; the food: a berry, its glint the pulsing entry (C_FOOD_HI)
sn_food_art:
        .byte 0, 0, 0, 0, 26, 0, 0, 0
        .byte 0, 0, 0, 26, 26, 0, 0, 0
        .byte 0, 0, 24, 24, 24, 24, 0, 0
        .byte 0, 24, 27, 24, 24, 24, 25, 0
        .byte 0, 24, 27, 24, 24, 24, 25, 0
        .byte 0, 24, 24, 24, 24, 25, 25, 0
        .byte 0, 0, 24, 25, 25, 25, 0, 0
        .byte 0, 0, 0, 0, 0, 0, 0, 0
; the block font's letters A-Z, 7 rows of 5 dots (bit 0 the left)
sn_letters:
        .byte 0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11   ; A
        .byte 0, 0, 0, 0, 0, 0, 0                        ; B
        .byte 0, 0, 0, 0, 0, 0, 0                        ; C
        .byte 0x0F, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0F   ; D
        .byte 0x1F, 0x01, 0x01, 0x0F, 0x01, 0x01, 0x1F   ; E
        .byte 0, 0, 0, 0, 0, 0, 0                        ; F
        .byte 0x0E, 0x11, 0x01, 0x1D, 0x11, 0x11, 0x0E   ; G
        .byte 0, 0, 0, 0, 0, 0, 0                        ; H
        .byte 0, 0, 0, 0, 0, 0, 0                        ; I
        .byte 0, 0, 0, 0, 0, 0, 0                        ; J
        .byte 0x11, 0x09, 0x05, 0x03, 0x05, 0x09, 0x11   ; K
        .byte 0, 0, 0, 0, 0, 0, 0                        ; L
        .byte 0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11   ; M
        .byte 0x11, 0x13, 0x15, 0x19, 0x11, 0x11, 0x11   ; N
        .byte 0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E   ; O
        .byte 0x0F, 0x11, 0x11, 0x0F, 0x01, 0x01, 0x01   ; P
        .byte 0, 0, 0, 0, 0, 0, 0                        ; Q
        .byte 0x0F, 0x11, 0x11, 0x0F, 0x05, 0x09, 0x11   ; R
        .byte 0x1E, 0x01, 0x01, 0x0E, 0x10, 0x10, 0x0F   ; S
        .byte 0, 0, 0, 0, 0, 0, 0                        ; T
        .byte 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E   ; U
        .byte 0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04   ; V
        .byte 0, 0, 0, 0, 0, 0, 0                        ; W
        .byte 0, 0, 0, 0, 0, 0, 0                        ; X
        .byte 0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04   ; Y
        .byte 0, 0, 0, 0, 0, 0, 0                        ; Z
        .align 4
; the palette: (entry, RGB 5:6:5) to a 0 entry, then the body's 16
sn_pal: .half 16, 0x1223, 17, 0x1A84, 18, 0x79E5, 19, 0xACAF
        .half 20, 0x18E6, 21, 0xE739, 22, 0x7C14, 23, 0x5B32
        .half 24, 0xD8E6, 25, 0x8043, 26, 0x3E47, 27, 0xFE59
        .half 28, 0xFEE7, 29, 0xFFFF, 30, 0x0000, 31, 0xFFFF
        .half 48, 0x28A8, 49, 0xCCBF, 50, 0xFFFF, 51, 0xF945
        .half 52, 0x08A2, 0, 0
sn_body:
        .word 0x2CA5, 0x3D05, 0x5546, 0x65A6, 0x7DE7, 0x8E48, 0xA688, 0xB6E9
        .word 0xCF2A, 0xB6E9, 0xA688, 0x8E48, 0x7DE7, 0x65A6, 0x5546, 0x3D05
sn_glint:
        .word 0x8947, 0x91A9, 0x9A0A, 0xA26C, 0xAAED, 0xAB4F, 0xB3B0, 0xBC12
        .word 0xC493, 0xCCF5, 0xD556, 0xDDB8, 0xE639, 0xE69B, 0xEEFC, 0xF75E
; the ripple: a sine's rows (-2..2) as descriptor offsets, 64 a turn
sn_ripple:
        .word 0, 0, 0, 0, 0, 80, 80, 80, 80, 80, 80, 80, 80, 80, 160, 160
        .word 160, 160, 160, 80, 80, 80, 80, 80, 80, 80, 80, 80, 0, 0, 0, 0
        .word 0, -80, -80, -80, -80, -80, -160, -160, -160, -160, -160, -160, -160, -160, -160, -160
        .word -160, -160, -160, -160, -160, -160, -160, -160, -160, -160, -160, -80, -80, -80, -80, -80
sn_seed:
        .word 2026

s_snake:        .asciz "SNAKE"
s_press:        .asciz "PRESS SPACE TO START"
s_keys:         .asciz "ARROWS STEER  P PAUSE  A AUTO"
s_score:        .asciz "SCORE"
s_score_:       .asciz "SCORE "
s_len:          .asciz "LEN"
s_best:         .asciz "BEST"
s_paused:       .asciz "PAUSED"
s_goon:         .asciz "P TO GO ON"
s_gameover:     .asciz "GAME OVER"
s_ready:        .asciz "READY"
s_steer:        .asciz "ARROWS TO STEER"
s_done:         .asciz "@done\n"
s_title:        .asciz "title"
s_game:         .asciz "game"
s_game_over:    .asciz "game_over"
s_title_draw:   .asciz "title_draw"
s_game_frame:   .asciz "game_frame"
s_step_avg:     .asciz "step_draw_avg"
s_step_max:     .asciz "step_draw_max"
s_board:        .asciz "board_draw"
s_fill_cell:    .asciz "fill_cell_8x8"
s_step_cells:   .asciz "step_cells"
s_field_fill:   .asciz "field_fill"
s_field_blit:   .asciz "field_blit"
s_full_redraw:  .asciz "full_redraw"
s_snake_redraw: .asciz "snake_redraw"
s_palette:      .asciz "palette_frame"
s_digits:       .asciz "digits_text"
s_desc:         .asciz "desc_480"
s_ripple:       .asciz "ripple"

        .bss
        .align 4
sn_state:       .space 64       ; the variables at r14 (S_)
sn_target:      .space 4        ; where drawing goes
sn_pmask:       .space 16
sn_from:        .space 20
sn_nib:         .space 64
sn_solid:       .space 256
sn_food_img:    .space 64
sn_food_mask:   .space 64
sn_turns:       .space 16
sn_nturns:      .space 4
sn_flash:       .space 4
sn_stamp:       .space 4
sn_step_sum:    .space 4
sn_step_max:    .space 4
sn_step_n:      .space 4
sn_t0:          .space 4
sn_t_space:     .space 4        ; the frame the game was started in
sn_event:       .space 28
sn_bt_c:        .space 4
sn_bt_in:       .space 4
sn_bt_i:        .space 4
sn_bt_col:      .space 4
sn_bt_dotc:     .space 4
sn_buf:         .space 20
sn_line:        .space 32
sn_queue:       .space 256      ; room's queue: cell indices, halves
sn_seen:        .space GH * 64 * 2
sn_grid:        .space GH * 64  ; the grid, 64 a row: G_
sn_sx:          .space RING     ; the snake's cells, a ring
sn_sy:          .space RING
