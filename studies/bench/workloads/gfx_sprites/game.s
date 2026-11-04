; gfx_sprites: a 2D game's frames (workload.py says what it stands for).
; This file is the game: start-up, the frame loop, the sprites' moves and
; hits, scrolling, and the status line; kernels.s has the drawing.
;
; The screen is SW x SH: the playfield, PH rows of the map's tiles, then
; the status line, 16 rows. The playfield shows the map from pixel ox,
; which grows by 8 (a word) each scroll; the map is MAPW tiles wide and
; wraps. Sprites are 16 x 16 and move within -8...SW - 8 across and
; -8...PH - 8 down, bouncing back off the ends, so up to half of one can
; be off the playfield, and is clipped: rows above or below it aren't
; drawn, nor words left or right of it.
;
; A sprite (32 bytes):
;   S_X, S_Y, S_VX, S_VY   where it is, and its move a frame
;   S_KIND                 its object: kinds S_KIND and S_KIND + 1 are its
;                          two frames of animation, four frames each
;   S_AT, S_N, S_ROWS      what's saved under it: the screen's address of
;                          the first word, the words a row and the rows
;                          (S_AT 0: nothing, the sprite was off the playfield)
; and 192 bytes at under + 192 i for what's under sprite i.

PH = SH - 16                    ; the playfield's rows
W = SW / 8                      ; words a row of the screen
MAPW = 64
PITCH = 320
S_X = 0
S_Y = 4
S_VX = 8
S_VY = 12
S_KIND = 16
S_AT = 20
S_N = 24
S_ROWS = 28
S_SIZE = 32
UNDER = 192                     ; 16 rows of 3 words
STATUS_FG = 14
STATUS_BG = 1
RANGE = 32                      ; a hit: this near the player

        .global main
        .far fb, shifted, tiles, tilemap, actors, under

        .text

main:   PUSH r7
        MOV  r1, #STATUS_FG
        MOV  r2, #STATUS_BG
        BSR  text_init
        BSR  preshift
        BSR  load_actors
        BSR  draw_map
        BSR  draw_status
        BSR  draw_sprites
.frame: BSR  erase_sprites      ; a frame
        MOV  r0, [frame]
        AND  r0, #SCROLL - 1
        CMP  r0, #SCROLL - 1
        BNE  .move
        BSR  scroll
.move:  MOV  r0, [frame]        ; the animation's frame: four of each
        LSR  r0, #2
        AND  r0, #1
        MOV  [fbit], r0
        BSR  move_sprites
        BSR  collide
        BSR  draw_sprites
        MOV  r0, [frame]
        INC  r0
        MOV  [frame], r0
        BSR  status_numbers
        MOV  r0, [frame]
        CMP  r0, #FRAMES
        BLT  .frame
        LEA  r1, [pc + .score]  ; the results
        MOV  r2, [score]
        BSR  bench_report
        LEA  r1, [pc + .hits]
        MOV  r2, [hits]
        BSR  bench_report
        BSR  checksum
        PUSH r2
        MOV  r2, r1
        LEA  r1, [pc + .sum]
        BSR  bench_report
        POP  r2
        LEA  r1, [pc + .fl]
        BSR  bench_report
        JMP  [sp]+
.score: .asciz "score"
.hits:  .asciz "hits"
.sum:   .asciz "screen_sum"
.fl:    .asciz "screen_fletcher"
        .align 2

; load_actors(): the sprites from `actors`, five signed halves each
load_actors:
        MOV  r1, #actors
        MOV  r2, #sprites
        MOV  r3, #NSPR
.spr:   MOV  r4, #5
.field: MOV  r0, half [r1]
        ADD  r1, #2
        SXH  r0
        MOV  [r2]+, r0
        DBNZ r4, .field
        CLR  [r2]+              ; nothing saved
        ADD  r2, #S_SIZE - 24
        DBNZ r3, .spr
        RET

; draw_map(): the playfield, a tile at a time
draw_map:
        SAVE r7-r11
        MOV  r8, #fb            ; r8: a row of tiles' first word
        MOV  r9, #tilemap       ; r9: its tiles in the map
        MOV  r10, #PH / 16
.trow:  MOV  r11, #W / 2
        MOV  r3, r8
        MOV  r4, r9
.tile:  MOV  r1, r3
        MOV  r2, byte [r4]+
        LSL  r2, #7             ; 128 bytes a tile
        ADD  r2, #tiles
        PUSH r3
        PUSH r4
        BSR  tile_draw
        POP  r4
        POP  r3
        ADD  r3, #8
        DEC  r11
        BNE  .tile
        ADD  r8, #16 * PITCH
        ADD  r9, #MAPW
        DEC  r10
        BNE  .trow
        RESTORE r7-r11
        RET

; scroll(): the playfield 8 pixels left: all of it copied a word left,
; and the map's next column of half-tiles drawn in the last word
scroll:
        SAVE r7-r11
        MOV  r1, #fb
        MOV  r2, #fb + 4
        MOV  r3, #W - 1
        MOV  r4, #PH
        BSR  copy_words
        MOV  r0, [ox]
        ADD  r0, #8
        MOV  [ox], r0
        LSR  r0, #3             ; the map's word column now at the right
        ADD  r0, #W - 1
        AND  r0, #2 * MAPW - 1
        MOV  r8, r0
        AND  r8, #1
        LSL  r8, #2             ; r8: the half of the tile, a byte offset
        LSR  r0, #1
        MOV  r9, #tilemap
        ADD  r9, r0             ; r9: the column's tiles in the map
        MOV  r10, #fb + 4 * (W - 1)
        MOV  r11, #PH / 16
.tile:  MOV  r1, r10
        MOV  r2, byte [r9]
        LSL  r2, #7
        ADD  r2, #tiles
        ADD  r2, r8
        BSR  tile_column
        ADD  r9, #MAPW
        ADD  r10, #16 * PITCH
        DEC  r11
        BNE  .tile
        RESTORE r7-r11
        RET

; ---- sprites ------------------------------------------------------------------------

; draw_sprites(): every sprite, in order, each over the ones before
draw_sprites:
        SAVE r7-r9
        MOV  r8, #sprites
        MOV  r9, #under
.spr:   MOV  r1, r8
        MOV  r2, r9
        BSR  draw_sprite
        ADD  r8, #S_SIZE
        ADD  r9, #UNDER
        CMP  r8, #sprites + NSPR * S_SIZE
        BNE  .spr
        RESTORE r7-r9
        RET

; erase_sprites(): every sprite taken off, the last drawn first, by
; putting back what was under it
erase_sprites:
        SAVE r7-r9
        MOV  r8, #sprites + NSPR * S_SIZE
        MOV  r9, #under + NSPR * UNDER
.spr:   SUB  r8, #S_SIZE
        SUB  r9, #UNDER
        MOVS r1, [r8 + S_AT]
        BEQ  .next
        MOV  r2, r9
        MOV  r3, [r8 + S_N]
        MOV  r4, [r8 + S_ROWS]
        BSR  restore_rect
.next:  CMP  r8, #sprites
        BNE  .spr
        RESTORE r7-r9
        RET

; draw_sprite(s, buf): sprite s drawn, clipped to the playfield, what's
; under it saved in buf first. Rows r0...r1 of it are on the playfield,
; and of the words it covers (three, or two on a word), k0...k1; its art
; is its kind's shifted to its pixel p, from row r0's pair k0.
draw_sprite:
        SAVE r7-r12
        MOV  r8, r1             ; r8: the sprite, r9: the buffer
        MOV  r9, r2
        CLR  [r8 + S_AT]
        MOV  r2, [r8 + S_Y]     ; r10: r0; r11: rows
        CLR  r10
        TST  r2, r2
        BPL  .top
        MOV  r10, r2
        NEG  r10
.top:   MOV  r11, #PH
        SUB  r11, r2
        CMP  r11, #16
        BLE  .bot
        MOV  r11, #16
.bot:   SUB  r11, r10
        BLE  .done              ; above or below the playfield
        MOV  r3, [r8 + S_X]
        MOV  r12, r3
        AND  r12, #7            ; r12: p
        ASR  r3, #3             ; r3: the first word it covers
        MOV  r5, #3             ; r5: k1, at most 3 (2 on a word) and W - word
        TST  r12, r12
        BNE  .k1
        MOV  r5, #2
.k1:    MOV  r0, #W
        SUB  r0, r3
        CMP  r5, r0
        BLE  .k0
        MOV  r5, r0
.k0:    CLR  r4                 ; r4: k0, -word if that's left of the screen
        TST  r3, r3
        BPL  .n
        MOV  r4, r3
        NEG  r4
.n:     SUB  r5, r4             ; r5: n, the words a row
        BLE  .done
        ; r6: the screen's address, row y + r0's word + k0
        ADD  r3, r4
        LSL  r3, #2
        MOV  r1, r2
        ADD  r1, r10
        BSR  row_addr
        ADD  r1, r3
        MOV  r6, r1
        ; the art: shifted + (8 kind + p) x 384 + 24 r0 + 8 k0
        MOV  r7, [r8 + S_KIND]
        OR   r7, [fbit]
        LSL  r7, #3
        ADD  r7, r12
        MOV  r0, r7
        LSL  r7, #8
        LSL  r0, #7
        ADD  r7, r0
        MOV  r0, r10
        LSL  r0, #3
        ADD  r7, r0
        LSL  r0, #1
        ADD  r7, r0
        LSL  r4, #3
        ADD  r7, r4
        ADD  r7, #shifted
        MOV  r12, r7            ; r12: the art (r7 is the calls' link)
        ; save under it, then draw it
        MOV  [r8 + S_AT], r6
        MOV  [r8 + S_N], r5
        MOV  [r8 + S_ROWS], r11
        MOV  r1, r9
        MOV  r2, r6
        MOV  r3, r5
        MOV  r4, r11
        BSR  save_rect
        MOV  r1, r6
        MOV  r2, r12
        MOV  r3, r5
        MOV  r4, r11
        BSR  sprite_draw
.done:  RESTORE r7-r12
        RET

; move_sprites(): every sprite moved by its speed; one that passes an end
; of its range is reflected back into it and turns round
move_sprites:
        MOV  r1, #sprites
        MOV  r2, #NSPR
.spr:   MOV  r3, [r1 + S_X]
        ADD  r3, [r1 + S_VX]
        CMP  r3, #-8
        BGE  .xmax
        MOV  r0, #-16           ; x = -8 - (x + 8)
        SUB  r0, r3
        MOV  r3, r0
        BRA  .xturn
.xmax:  CMP  r3, #SW - 8
        BLE  .xok
        MOV  r0, #2 * (SW - 8)
        SUB  r0, r3
        MOV  r3, r0
.xturn: MOV  r0, [r1 + S_VX]
        NEG  r0
        MOV  [r1 + S_VX], r0
.xok:   MOV  [r1 + S_X], r3
        MOV  r3, [r1 + S_Y]
        ADD  r3, [r1 + S_VY]
        CMP  r3, #-8
        BGE  .ymax
        MOV  r0, #-16
        SUB  r0, r3
        MOV  r3, r0
        BRA  .yturn
.ymax:  CMP  r3, #PH - 8
        BLE  .yok
        MOV  r0, #2 * (PH - 8)
        SUB  r0, r3
        MOV  r3, r0
.yturn: MOV  r0, [r1 + S_VY]
        NEG  r0
        MOV  [r1 + S_VY], r0
.yok:   MOV  [r1 + S_Y], r3
        ADD  r1, #S_SIZE
        DEC  r2
        BNE  .spr
        RET

; collide(): every other sprite less than RANGE pixels from the player
; (sprite 0) across and down is a hit, worth 25 + its kind
collide:
        MOV  r1, #sprites + S_SIZE
        MOV  r2, #NSPR - 1
        MOV  r5, [sprites + S_X]
        MOV  r6, [sprites + S_Y]
.spr:   MOV  r3, [r1 + S_X]
        SUB  r3, r5
        CMP  r3, #-RANGE
        BLE  .next
        CMP  r3, #RANGE
        BGE  .next
        MOV  r3, [r1 + S_Y]
        SUB  r3, r6
        CMP  r3, #-RANGE
        BLE  .next
        CMP  r3, #RANGE
        BGE  .next
        MOV  r0, [hits]
        INC  r0
        MOV  [hits], r0
        MOV  r0, [r1 + S_KIND]
        OR   r0, [fbit]
        ADD  r0, #25
        ADD  r0, [score]
        MOV  [score], r0
.next:  ADD  r1, #S_SIZE
        DEC  r2
        BNE  .spr
        RET

; ---- the status line --------------------------------------------------------------------

; draw_status(): the status line's background, and all its text
draw_status:
        PUSH r7
        MOV  r1, #fb + PH * PITCH
        MOV  r2, #0x11111111 * STATUS_BG
        MOV  r3, #W
        MOV  r4, #16
        BSR  fill_words
        MOV  r1, #2
        MOV  r2, #PH + 1
        MOV  r3, #status
        MOV  r4, #STATUS_LEN
        BSR  draw_cells
        JMP  [sp]+

; status_numbers(): the score, the hits and the frame, in decimal, into
; the status line's text and redrawn
status_numbers:
        PUSH r7
        MOV  r1, #status + 6
        MOV  r2, [score]
        MOV  r3, #6
        BSR  decimal
        MOV  r1, #2 + 7 * 6
        MOV  r2, #PH + 1
        MOV  r3, #status + 6
        MOV  r4, #6
        BSR  draw_cells
        MOV  r1, #status + 19
        MOV  r2, [hits]
        MOV  r3, #4
        BSR  decimal
        MOV  r1, #2 + 7 * 19
        MOV  r2, #PH + 1
        MOV  r3, #status + 19
        MOV  r4, #4
        BSR  draw_cells
        MOV  r1, #status + 31
        MOV  r2, [frame]
        MOV  r3, #4
        BSR  decimal
        MOV  r1, #2 + 7 * 31
        MOV  r2, #PH + 1
        MOV  r3, #status + 31
        MOV  r4, #4
        BSR  draw_cells
        JMP  [sp]+

; decimal(s, v, n): v's last n decimal digits at s
decimal:
        ADD  r1, r3
        MOV  r4, #10
.digit: DIVU r0:r2, r4
        ADD  r0, #'0'
        DEC  r1
        MOV  byte [r1], r0
        DBNZ r3, .digit
        RET

        .data
        .align 4
frame:  .word 0                 ; frames done
fbit:   .word 0                 ; the animation's frame, 0 or 1
ox:     .word 0                 ; the map's pixel at the playfield's left
score:  .word 0
hits:   .word 0
status: .ascii "SCORE 000000  HITS 0000  FRAME 0000"
STATUS_LEN = 35
        .align 4

        .bss
        .align 4
sprites: .space S_SIZE * NSPR

        .section .farbss.under
        .align 4
under:  .space UNDER * NSPR
