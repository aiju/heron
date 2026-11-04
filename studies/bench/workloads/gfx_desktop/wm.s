; gfx_desktop: a window system redrawing a desktop (workload.py says what
; it stands for). This file is the window manager: the windows and their
; stacking order, visible regions as lists of rectangles, redrawing a
; damaged area layer by layer, the session's actions, and the software
; cursor. kernels.s has the fills and copies, text.s the text.
;
; Everything is clipped through `clip` (kernels.s): a redraw sets it to
; one rectangle of a window's visible region at a time and draws the
; whole window, and every primitive drops what falls outside it.
;
; A window (128 bytes), from the session's record:
;   W_X, W_Y, W_W, W_H     the frame's rectangle
;   W_KIND                 0 a terminal, 1 a document
;   W_TCOL, W_CCOL, W_FG   the title bar's, the client area's and the text's colours
;   W_FIRST                its first corpus line
;   W_EDIT                 a document's edit line
;   W_COLS, W_ROWS         a terminal's cells
;   W_TITLE, W_TLEN        the title
;   W_TOP                  a terminal's top line, as it scrolls
;   W_NTEXT, W_TEXT        a document's edit line: what's been typed
;   W_SEL                  a document's selection: x0, y0, x1, y1 in the client area
;
; Its layout: a 1-pixel black frame; a title bar 16 rows high, then a black
; line; the client area inside the rest. A terminal's cells start 2 pixels
; right and 1 below the client area's corner; a document's lines 15 rows
; apart from 2 below it, 4 pixels in. Rectangles are x0, y0, x1, y1, the
; last two just outside, in four words.

PITCH = 320
W_X = 0
W_Y = 4
W_W = 8
W_H = 12
W_KIND = 16
W_TCOL = 20
W_CCOL = 24
W_FG = 28
W_FIRST = 32
W_EDIT = 36
W_COLS = 40
W_ROWS = 44
W_TITLE = 48
W_TLEN = 52
W_TOP = 56
W_NTEXT = 60
W_SEL = 64
W_TEXT = 80
W_SIZE = 128
NWMAX = 8
EDIT_MAX = 40
LINE_H = 15
CELL_W = 7
MAXLINES = 128
MAXRECTS = 128
OP_CURSOR = 1
BG_EVEN = 0x36363636            ; the background's two rows
BG_ODD = 0x63636363

        .global main
        .far fb, corpus, session, cursor_art

        .text

main:   PUSH r7
        BSR  text_init
        BSR  corpus_split
        BSR  session_load
        MOV  r1, #screen        ; draw everything, then the cursor
        BSR  repaint
        MOV  r1, [cur_x]
        MOV  r2, [cur_y]
        BSR  cursor_show
.op:    MOV  r1, [nops]         ; then the session
        DEC  r1
        BMI  .end
        MOV  [nops], r1
        MOV  r1, [ops]
        MOV  r0, r1
        ADD  r0, #12
        MOV  [ops], r0
        BSR  do_op
        BRA  .op
.end:   BSR  checksum
        PUSH r2
        MOV  r2, r1
        LEA  r1, [pc + .sum]
        BSR  bench_report
        POP  r2
        LEA  r1, [pc + .fl]
        BSR  bench_report
        JMP  [sp]+
.sum:   .asciz "screen_sum"
.fl:    .asciz "screen_fletcher"
        .align 2

; ---- setting up ----------------------------------------------------------------

; corpus_split(): the corpus's lines, each its address and length, in lines
corpus_split:
        MOV  r1, #corpus        ; r1: where we are
        MOV  r2, r1
        ADD  r2, [corpus_len]   ; r2: the end
        MOV  r3, #lines         ; r3: the next entry
        CLR  r4                 ; r4: lines
.line:  CMP  r1, r2
        BHS  .done
        MOV  r5, r1             ; r5: the line's start
.scan:  CMP  r1, r2
        BHS  .end
        MOV  r0, byte [r1]+
        CMP  r0, #10
        BNE  .scan
        MOV  r0, r1             ; past the newline
        DEC  r0
        BRA  .add
.end:   MOV  r0, r1
.add:   SUB  r0, r5
        MOV  [r3]+, r5
        MOV  [r3]+, r0
        INC  r4
        BRA  .line
.done:  MOV  [nlines], r4
        RET

; session_load(): the windows from the session, back to front in order,
; the cursor's place, and where the actions start
session_load:
        SAVE r8-r9
        MOV  r8, #session
        MOV  r0, half [r8]
        MOV  [nwin], r0
        MOV  r9, r0             ; r9: windows left
        MOV  r0, half [r8 + 2]
        MOV  [nops], r0
        MOV  r0, half [r8 + 4]
        MOV  [cur_x], r0
        MOV  r0, half [r8 + 6]
        MOV  [cur_y], r0
        ADD  r8, #16            ; r8: a window's record
        MOV  r1, #wins          ; r1: the window
        CLR  r2                 ; r2: its number
.win:   MOV  r3, r8             ; twelve halves to twelve words
        MOV  r4, r1
        MOV  r5, #12
.field: MOV  r0, half [r3]
        ADD  r3, #2
        MOV  [r4]+, r0
        DBNZ r5, .field
        MOV  [r1 + W_TITLE], r3 ; the title follows
        CLR  r4
.tlen:  MOVS r0, byte [r3 + r4]
        BEQ  .tl
        INC  r4
        BRA  .tlen
.tl:    MOV  [r1 + W_TLEN], r4
        MOV  r0, [r1 + W_FIRST]
        MOV  [r1 + W_TOP], r0
        MOV  [order + r2*4], r2
        ADD  r8, #48
        ADD  r1, #W_SIZE
        INC  r2
        DEC  r9
        BNE  .win
        MOV  [ops], r8
        RESTORE r8-r9
        RET

; ---- rectangles ------------------------------------------------------------------

; rect_and(a, b, out): out = a & b; r1 = 1 if it isn't empty, else 0.
; out may be a or b.
rect_and:
        MOV  r0, [r1]
        CMP  r0, [r2]
        BGE  .1
        MOV  r0, [r2]
.1:     MOV  r4, [r1 + 4]
        CMP  r4, [r2 + 4]
        BGE  .2
        MOV  r4, [r2 + 4]
.2:     MOV  r5, [r1 + 8]
        CMP  r5, [r2 + 8]
        BLE  .3
        MOV  r5, [r2 + 8]
.3:     MOV  r6, [r1 + 12]
        CMP  r6, [r2 + 12]
        BLE  .4
        MOV  r6, [r2 + 12]
.4:     MOV  [r3], r0
        MOV  [r3 + 4], r4
        MOV  [r3 + 8], r5
        MOV  [r3 + 12], r6
        CLR  r1
        CMP  r5, r0
        BLE  .empty
        CMP  r6, r4
        BLE  .empty
        INC  r1
.empty: RET

; win_rect(w, out): out = the window's rectangle
win_rect:
        MOV  r0, [r1 + W_X]
        MOV  [r2], r0
        ADD  r0, [r1 + W_W]
        MOV  [r2 + 8], r0
        MOV  r0, [r1 + W_Y]
        MOV  [r2 + 4], r0
        ADD  r0, [r1 + W_H]
        MOV  [r2 + 12], r0
        RET

; subtract(src, n, dst, r): the n rectangles at src less r, into dst:
; each that meets r leaves up to four pieces, the bands above and below r
; and the pieces left and right of it between them. r1 = how many.
subtract:
        SAVE r8-r14
        MOV  r8, [r4]           ; r8-r11: r
        MOV  r9, [r4 + 4]
        MOV  r10, [r4 + 8]
        MOV  r11, [r4 + 12]
        MOV  r12, r3            ; r12: the next out, r13 the first
        MOV  r13, r3
        TST  r2, r2
        BEQ  .done
.rect:  MOV  r3, [r1]           ; r3-r6: the rectangle a
        MOV  r4, [r1 + 4]
        MOV  r5, [r1 + 8]
        MOV  r6, [r1 + 12]
        ADD  r1, #16
        CMP  r5, r8             ; apart?
        BLE  .keep
        CMP  r3, r10
        BGE  .keep
        CMP  r6, r9
        BLE  .keep
        CMP  r4, r11
        BGE  .keep
        CMP  r4, r9             ; the band above r
        BGE  .below
        MOV  [r12]+, r3
        MOV  [r12]+, r4
        MOV  [r12]+, r5
        MOV  [r12]+, r9
        MOV  r4, r9             ; what's left starts at r's top
.below: CMP  r11, r6            ; the band below
        BGE  .left
        MOV  [r12]+, r3
        MOV  [r12]+, r11
        MOV  [r12]+, r5
        MOV  [r12]+, r6
        MOV  r6, r11            ; and ends at r's bottom
.left:  CMP  r3, r8             ; left of r, between the bands
        BGE  .right
        MOV  [r12]+, r3
        MOV  [r12]+, r4
        MOV  [r12]+, r8
        MOV  [r12]+, r6
.right: CMP  r10, r5            ; right of it
        BGE  .next
        MOV  [r12]+, r10
        MOV  [r12]+, r4
        MOV  [r12]+, r5
        MOV  [r12]+, r6
        BRA  .next
.keep:  MOV  [r12]+, r3
        MOV  [r12]+, r4
        MOV  [r12]+, r5
        MOV  [r12]+, r6
.next:  DEC  r2
        BNE  .rect
.done:  MOV  r1, r12
        SUB  r1, r13
        LSR  r1, #4
        RESTORE r8-r14
        RET

; visible(k): the visible region of layer k of the stack (-1 for the
; background): its rectangle (the screen's) less every window above it.
; r1 = how many rectangles, r2 = where (one of the two lists, ping-ponged
; through the subtractions).
visible:
        SAVE r7-r12
        SUB  sp, #16            ; [sp]: a window's rectangle
        MOV  r8, r1             ; r8: the layer
        MOV  r9, #rl_a          ; r9: the list, r10 the other
        MOV  r10, #rl_b
        TST  r8, r8
        BPL  .win
        MOV  r0, #screen        ; the background: the screen
        MOV  r1, [r0]
        MOV  [r9], r1
        MOV  r1, [r0 + 4]
        MOV  [r9 + 4], r1
        MOV  r1, [r0 + 8]
        MOV  [r9 + 8], r1
        MOV  r1, [r0 + 12]
        MOV  [r9 + 12], r1
        BRA  .start
.win:   MOV  r1, [order + r8*4]
        LSL  r1, #7
        ADD  r1, #wins
        MOV  r2, r9
        BSR  win_rect
.start: MOV  r11, #1            ; r11: rectangles
.above: INC  r8                 ; each window above
        CMP  r8, [nwin]
        BGE  .done
        MOV  r1, [order + r8*4]
        LSL  r1, #7
        ADD  r1, #wins
        MOV  r2, sp
        BSR  win_rect
        MOV  r1, r9
        MOV  r2, r11
        MOV  r3, r10
        MOV  r4, sp
        BSR  subtract
        MOV  r11, r1
        MOV  r0, r9             ; the result is the list now
        MOV  r9, r10
        MOV  r10, r0
        TST  r11, r11
        BNE  .above
.done:  MOV  r1, r11
        MOV  r2, r9
        ADD  sp, #16
        RESTORE r7-r12
        RET

; zpos(w): r1 = the window's place in the stack, 0 the back
zpos:
        SUB  r1, #wins
        LSR  r1, #7             ; its number
        CLR  r0
.find:  CMP  r1, [order + r0*4]
        BEQ  .found
        INC  r0
        BRA  .find
.found: MOV  r1, r0
        RET

; ---- redrawing -------------------------------------------------------------------

; repaint(r): the area r redrawn: every layer from the back, clipped to
; each rectangle of its visible region that meets r. The regions don't
; overlap, so every pixel is drawn once, by the layer that shows there.
; The frame: [sp] r, [sp + 16] the layer.
repaint:
        SAVE r7-r14
        SUB  sp, #20
        MOV  r0, [r1]
        MOV  [sp], r0
        MOV  r0, [r1 + 4]
        MOV  [sp + 4], r0
        MOV  r0, [r1 + 8]
        MOV  [sp + 8], r0
        MOV  r0, [r1 + 12]
        MOV  [sp + 12], r0
        MOV  r0, #-1
        MOV  [sp + 16], r0
.layer: MOV  r1, [sp + 16]
        BSR  visible
        MOV  r8, r1             ; r8: rectangles left, r9 the next
        MOV  r9, r2
.rect:  DEC  r8
        BMI  .next
        MOV  r1, r9
        ADD  r9, #16
        MOV  r2, sp
        MOV  r3, #clip_x0
        BSR  rect_and
        TST  r1, r1
        BEQ  .rect
        MOV  r1, [sp + 16]
        BSR  draw_layer
        BRA  .rect
.next:  MOV  r0, [sp + 16]
        INC  r0
        MOV  [sp + 16], r0
        CMP  r0, [nwin]
        BLT  .layer
        ADD  sp, #20
        RESTORE r7-r14
        RET

; draw_layer(k): layer k of the stack, within the clip: the background's
; pattern for -1, else the window
draw_layer:
        TST  r1, r1
        BPL  .win
        PUSH r7
        MOV  r0, #BG_EVEN
        MOV  [fill_pat], r0
        MOV  r0, #BG_ODD
        MOV  [fill_pat + 4], r0
        MOV  r1, [clip_x0]
        MOV  r2, [clip_y0]
        MOV  r3, [clip_x1]
        MOV  r4, [clip_y1]
        BSR  fill_rect
        JMP  [sp]+
.win:   MOV  r1, [order + r1*4]
        LSL  r1, #7
        ADD  r1, #wins
        JMP  draw_window

; set_fill(c): fill_rect's pattern a solid colour
set_fill:
        MOV  r0, [solid + r1*4]
        MOV  [fill_pat], r0
        MOV  [fill_pat + 4], r0
        RET

; clip_and(x0, y0, x1, y1): the clip cut to the rectangle as well
clip_and:
        CMP  r1, [clip_x0]
        BLT  .1
        MOV  [clip_x0], r1
.1:     CMP  r2, [clip_y0]
        BLT  .2
        MOV  [clip_y0], r2
.2:     CMP  r3, [clip_x1]
        BGT  .3
        MOV  [clip_x1], r3
.3:     CMP  r4, [clip_y1]
        BGT  .4
        MOV  [clip_y1], r4
.4:     RET

; draw_window(w): the window, within the clip: its frame, title bar and
; title, client area, and what it shows. The frame: [sp] the clip as it
; came, to put back.
draw_window:
        SAVE r7-r14
        SUB  sp, #16
        MOV  r0, [clip_x0]
        MOV  [sp], r0
        MOV  r0, [clip_y0]
        MOV  [sp + 4], r0
        MOV  r0, [clip_x1]
        MOV  [sp + 8], r0
        MOV  r0, [clip_y1]
        MOV  [sp + 12], r0
        MOV  r8, r1             ; r8: the window
        MOV  r9, [r8 + W_X]     ; r9, r10: its top left corner
        MOV  r10, [r8 + W_Y]
        MOV  r11, r9            ; r11, r12: its bottom right, outside
        ADD  r11, [r8 + W_W]
        MOV  r12, r10
        ADD  r12, [r8 + W_H]
        ; the frame: four lines of black
        CLR  r1
        BSR  set_fill
        MOV  r1, r9
        MOV  r2, r10
        MOV  r3, r11
        MOV  r4, r10
        INC  r4
        BSR  fill_rect
        MOV  r1, r9
        MOV  r2, r12
        DEC  r2
        MOV  r3, r11
        MOV  r4, r12
        BSR  fill_rect
        MOV  r1, r9
        MOV  r2, r10
        MOV  r3, r9
        INC  r3
        MOV  r4, r12
        BSR  fill_rect
        MOV  r1, r11
        DEC  r1
        MOV  r2, r10
        MOV  r3, r11
        MOV  r4, r12
        BSR  fill_rect
        ; the title bar, and the black line under it
        MOV  r1, [r8 + W_TCOL]
        BSR  set_fill
        MOV  r1, r9
        INC  r1
        MOV  r2, r10
        INC  r2
        MOV  r3, r11
        DEC  r3
        MOV  r4, r10
        ADD  r4, #17
        BSR  fill_rect
        CLR  r1
        BSR  set_fill
        MOV  r1, r9
        INC  r1
        MOV  r2, r10
        ADD  r2, #17
        MOV  r3, r11
        DEC  r3
        MOV  r4, r10
        ADD  r4, #18
        BSR  fill_rect
        ; the title, in white, clipped to the bar
        MOV  r1, r9
        INC  r1
        MOV  r2, r10
        INC  r2
        MOV  r3, r11
        DEC  r3
        MOV  r4, r10
        ADD  r4, #17
        BSR  clip_and
        MOV  r0, #15
        MOV  [text_fg], r0
        MOV  r1, r9
        ADD  r1, #6
        MOV  r2, r10
        ADD  r2, #13
        MOV  r3, [r8 + W_TITLE]
        MOV  r4, [r8 + W_TLEN]
        BSR  draw_text
        BSR  .unclip
        ; the client area, and its contents clipped to it
        MOV  r1, [r8 + W_CCOL]
        BSR  set_fill
        MOV  r1, r9
        INC  r1
        MOV  r2, r10
        ADD  r2, #18
        MOV  r3, r11
        DEC  r3
        MOV  r4, r12
        DEC  r4
        BSR  fill_rect
        MOV  r1, r9
        INC  r1
        MOV  r2, r10
        ADD  r2, #18
        MOV  r3, r11
        DEC  r3
        MOV  r4, r12
        DEC  r4
        BSR  clip_and
        MOVS r0, [r8 + W_KIND]
        BNE  .doc

; a terminal: its rows that meet the clip, each its line in cells
        MOV  r1, [r8 + W_FG]
        MOV  r2, [r8 + W_CCOL]
        BSR  set_colours
        MOV  r13, r10           ; r13: a row's top
        ADD  r13, #19
        CLR  r14                ; r14: the row
.trow:  CMP  r14, [r8 + W_ROWS]
        BGE  .end
        CMP  r13, [clip_y1]
        BGE  .end
        MOV  r0, r13
        ADD  r0, #LINE_H
        CMP  r0, [clip_y0]
        BLE  .tnext
        MOV  r0, [r8 + W_TOP]   ; its line, the top's + the row, wrapped
        ADD  r0, r14
        CMP  r0, [nlines]
        BLT  .tline
        SUB  r0, [nlines]
.tline: LSL  r0, #3
        ADD  r0, #lines
        MOV  r3, [r0]
        MOV  r4, [r0 + 4]
        MOV  r1, [r8 + W_COLS]
        PUSH r1
        MOV  r1, r9
        ADD  r1, #3
        MOV  r2, r13
        BSR  draw_cells
        ADD  sp, #4
.tnext: ADD  r13, #LINE_H
        INC  r14
        BRA  .trow

; a document: its lines that start inside the client area and meet the
; clip, the edit line its own text; then its selection inverted
.doc:   MOV  r0, [r8 + W_FG]
        MOV  [text_fg], r0
        MOV  r13, r10           ; r13: a line's top
        ADD  r13, #20
        CLR  r14                ; r14: the line
.dline: MOV  r0, r12
        DEC  r0
        CMP  r13, r0
        BGE  .sel
        CMP  r13, [clip_y1]
        BGE  .sel
        MOV  r0, r13
        ADD  r0, #LINE_H
        CMP  r0, [clip_y0]
        BLE  .dnext
        CMP  r14, [r8 + W_EDIT]
        BNE  .corpus
        LEA  r3, [r8 + W_TEXT]
        MOV  r4, [r8 + W_NTEXT]
        BRA  .text
.corpus:
        MOV  r0, [r8 + W_FIRST]
        ADD  r0, r14
        CMP  r0, [nlines]
        BLT  .dl
        SUB  r0, [nlines]
.dl:    LSL  r0, #3
        ADD  r0, #lines
        MOV  r3, [r0]
        MOV  r4, [r0 + 4]
.text:  MOV  r1, r9
        ADD  r1, #5
        MOV  r2, r13
        ADD  r2, #12
        BSR  draw_text
.dnext: ADD  r13, #LINE_H
        INC  r14
        BRA  .dline
.sel:   LEA  r1, [r8 + W_SEL]
        BSR  sel_xor
.end:   BSR  .unclip
        ADD  sp, #16
        RESTORE r7-r14
        RET

; .unclip: the clip put back as it came (r0 used)
.unclip:
        MOV  r0, [sp]
        MOV  [clip_x0], r0
        MOV  r0, [sp + 4]
        MOV  [clip_y0], r0
        MOV  r0, [sp + 8]
        MOV  [clip_x1], r0
        MOV  r0, [sp + 12]
        MOV  [clip_y1], r0
        RET

; sel_xor(sel): window r8's selection at sel (in its client area)
; inverted, within the clip
sel_xor:
        MOV  r2, [r8 + W_X]
        INC  r2                 ; the client area's corner
        MOV  r4, [r8 + W_Y]
        ADD  r4, #18
        MOV  r0, r1
        MOV  r1, [r0]
        ADD  r1, r2
        MOV  r3, [r0 + 8]
        ADD  r3, r2
        MOV  r2, [r0 + 4]
        ADD  r2, r4
        ADD  r4, [r0 + 12]
        JMP  xor_rect

; ---- the session's actions ------------------------------------------------------------

; do_op(op): one action: the cursor moved, or the cursor taken off, the
; action done, and the cursor put back. An action is the code, the
; window, and four arguments, halves.
do_op:
        SAVE r7-r9
        MOV  r8, r1
        MOV  r9, half [r8]      ; r9: the code
        CMP  r9, #OP_CURSOR
        BNE  .act
        BSR  cursor_hide
        MOV  r1, half [r8 + 4]
        MOV  r2, half [r8 + 6]
        BSR  cursor_show
        BRA  .done
.act:   BSR  cursor_hide
        MOV  r1, half [r8 + 2]  ; the window
        LSL  r1, #7
        ADD  r1, #wins
        MOV  r2, r8
        CALL [optab + r9*4]
        MOV  r1, [cur_x]
        MOV  r2, [cur_y]
        BSR  cursor_show
.done:  RESTORE r7-r9
        RET

; op_move(w, op): the top window moved by dx, dy: a copy of all of it,
; then what it uncovered (its old rectangle less its new) redrawn. The
; frame: [sp] the old rectangle, [sp + 16] the new.
op_move:
        SAVE r7-r14
        SUB  sp, #32
        MOV  r8, r1
        MOV  r9, half [r2 + 4]  ; r9, r10: dx, dy
        SXH  r9
        MOV  r10, half [r2 + 6]
        SXH  r10
        MOV  r2, sp
        BSR  win_rect
        MOV  r0, [r8 + W_H]     ; copy_rect(x + dx, y + dy, x, y, w, h)
        PUSH r0
        MOV  r0, [r8 + W_W]
        PUSH r0
        MOV  r3, [r8 + W_X]
        MOV  r4, [r8 + W_Y]
        MOV  r1, r3
        ADD  r1, r9
        MOV  r2, r4
        ADD  r2, r10
        MOV  [r8 + W_X], r1
        MOV  [r8 + W_Y], r2
        BSR  copy_rect
        ADD  sp, #8
        MOV  r1, r8
        LEA  r2, [sp + 16]
        BSR  win_rect
        MOV  r1, sp             ; uncovered: old less new
        MOV  r2, #1
        MOV  r3, #exposed
        LEA  r4, [sp + 16]
        BSR  subtract
        MOV  r9, r1
        MOV  r10, #exposed
.each:  DEC  r9
        BMI  .done
        MOV  r1, r10
        BSR  repaint
        ADD  r10, #16
        BRA  .each
.done:  ADD  sp, #32
        RESTORE r7-r14
        RET

; op_scroll(w): a terminal's lines up by one, a new one at the bottom.
; In each rectangle of its visible region that meets its cells, the rows
; below the first line are copied up a line, and the last line's rows
; (all of it, if it's no more than a line high) redrawn. The frame: [sp]
; its cells' rectangle, [sp + 16] the piece in hand.
op_scroll:
        SAVE r7-r14
        SUB  sp, #32
        MOV  r8, r1             ; r8: the window
        MOV  r0, [r8 + W_TOP]   ; the next line at the top
        INC  r0
        CMP  r0, [nlines]
        BLT  .top
        CLR  r0
.top:   MOV  [r8 + W_TOP], r0
        MOV  r0, [r8 + W_X]     ; the cells: 7 x cols by 15 x rows
        ADD  r0, #3
        MOV  [sp], r0
        MOV  r1, [r8 + W_COLS]
        MOV  r2, r1
        LSL  r1, #3
        SUB  r1, r2
        ADD  r0, r1
        MOV  [sp + 8], r0
        MOV  r0, [r8 + W_Y]
        ADD  r0, #19
        MOV  [sp + 4], r0
        MOV  r1, [r8 + W_ROWS]
        MOV  r2, r1
        LSL  r1, #4
        SUB  r1, r2
        ADD  r0, r1
        MOV  [sp + 12], r0
        MOV  r1, r8
        BSR  zpos
        BSR  visible
        MOV  r9, r1             ; r9: rectangles left, r10 the next
        MOV  r10, r2
.each:  DEC  r9
        BMI  .done
        MOV  r1, r10
        ADD  r10, #16
        MOV  r2, sp
        LEA  r3, [sp + 16]
        BSR  rect_and
        TST  r1, r1
        BEQ  .each
        MOV  r11, [sp + 16]     ; r11-r14: the piece
        MOV  r12, [sp + 20]
        MOV  r13, [sp + 24]
        MOV  r14, [sp + 28]
        MOV  r0, r14
        SUB  r0, r12
        SUB  r0, #LINE_H        ; rows to copy
        BLE  .redraw
        PUSH r0                 ; copy_rect(x0, y0, x0, y0 + 15, w, h - 15)
        MOV  r0, r13
        SUB  r0, r11
        PUSH r0
        MOV  r1, r11
        MOV  r2, r12
        MOV  r3, r11
        MOV  r4, r12
        ADD  r4, #LINE_H
        BSR  copy_rect
        ADD  sp, #8
        MOV  r12, r14           ; and the last line's rows to redraw
        SUB  r12, #LINE_H
.redraw:
        MOV  [clip_x0], r11
        MOV  [clip_y0], r12
        MOV  [clip_x1], r13
        MOV  [clip_y1], r14
        MOV  r1, r8
        BSR  draw_window
        BRA  .each
.done:  ADD  sp, #32
        RESTORE r7-r14
        RET

; op_raise(w): the window to the top of the stack, and all of it redrawn
op_raise:
        SAVE r7-r8
        SUB  sp, #16
        MOV  r8, r1
        BSR  zpos               ; the windows above it down one
        MOV  r2, [nwin]
        DEC  r2
.down:  CMP  r1, r2
        BGE  .top
        MOV  r0, [order + 4 + r1*4]
        MOV  [order + r1*4], r0
        INC  r1
        BRA  .down
.top:   MOV  r0, r8
        SUB  r0, #wins
        LSR  r0, #7
        MOV  [order + r2*4], r0
        MOV  r1, r8
        MOV  r2, sp
        BSR  win_rect
        MOV  r1, sp
        BSR  repaint
        ADD  sp, #16
        RESTORE r7-r8
        RET

; op_type(w, op): a character added to a document's edit line, and the
; line redrawn (the edit line's 15 rows, across the client area)
op_type:
        SAVE r7-r8
        SUB  sp, #16
        MOV  r8, r1
        MOV  r0, [r8 + W_NTEXT]
        CMP  r0, #EDIT_MAX
        BGE  .full
        MOV  r3, half [r2 + 4]
        LEA  r4, [r8 + W_TEXT]
        MOV  byte [r4 + r0], r3
        INC  r0
        MOV  [r8 + W_NTEXT], r0
.full:  MOV  r0, [r8 + W_X]
        INC  r0
        MOV  [sp], r0
        ADD  r0, [r8 + W_W]
        SUB  r0, #2
        MOV  [sp + 8], r0
        MOV  r0, [r8 + W_EDIT]
        MOV  r1, r0
        LSL  r0, #4
        SUB  r0, r1             ; 15 rows a line
        ADD  r0, [r8 + W_Y]
        ADD  r0, #20
        MOV  [sp + 4], r0
        ADD  r0, #LINE_H
        MOV  r1, [r8 + W_Y]     ; no lower than the client area
        ADD  r1, [r8 + W_H]
        DEC  r1
        CMP  r0, r1
        BLE  .in
        MOV  r0, r1
.in:    MOV  [sp + 12], r0
        CMP  r0, [sp + 4]
        BLE  .done
        MOV  r1, sp
        BSR  repaint
.done:  ADD  sp, #16
        RESTORE r7-r8
        RET

; op_select(w, op): a document's selection moved: in each rectangle of
; its visible region (cut to the client area), the old one inverted back
; and the new one inverted. The frame: [sp] the client area.
op_select:
        SAVE r7-r11
        SUB  sp, #16
        MOV  r8, r1
        MOV  r10, r2            ; r10: the action
        MOV  r0, [r8 + W_X]
        INC  r0
        MOV  [sp], r0
        ADD  r0, [r8 + W_W]
        SUB  r0, #2
        MOV  [sp + 8], r0
        MOV  r0, [r8 + W_Y]
        ADD  r0, #18
        MOV  [sp + 4], r0
        SUB  r0, #19
        ADD  r0, [r8 + W_H]
        MOV  [sp + 12], r0
        BSR  zpos
        BSR  visible
        MOV  r9, r1             ; r9: rectangles left, r11 the next
        MOV  r11, r2
.each:  DEC  r9
        BMI  .set
        MOV  r1, r11
        ADD  r11, #16
        MOV  r2, sp
        MOV  r3, #clip_x0
        BSR  rect_and
        TST  r1, r1
        BEQ  .each
        LEA  r1, [r8 + W_SEL]   ; the old
        BSR  sel_xor
        MOV  r0, r10            ; the new, from the action
        LEA  r1, [sel_new]
        MOV  r2, half [r0 + 4]
        MOV  [r1], r2
        MOV  r2, half [r0 + 6]
        MOV  [r1 + 4], r2
        MOV  r2, half [r0 + 8]
        MOV  [r1 + 8], r2
        MOV  r2, half [r0 + 10]
        MOV  [r1 + 12], r2
        BSR  sel_xor
        BRA  .each
.set:   MOV  r0, half [r10 + 4]
        MOV  [r8 + W_SEL], r0
        MOV  r0, half [r10 + 6]
        MOV  [r8 + W_SEL + 4], r0
        MOV  r0, half [r10 + 8]
        MOV  [r8 + W_SEL + 8], r0
        MOV  r0, half [r10 + 10]
        MOV  [r8 + W_SEL + 12], r0
        ADD  sp, #16
        RESTORE r7-r11
        RET

; ---- the cursor ------------------------------------------------------------------------

; cursor_show(x, y): the cursor drawn at (x, y), what was under it saved
; first: 16 rows of the three words it can touch. It is drawn shifted to
; its pixel: with s = 4 x (x mod 8), the image's and the mask's 64 bits a
; row become three words, (lo << s), (lo >> 32 - s | hi << s), (hi >> 32 -
; s), and d = (d & ~mask) | image. The cursor is always wholly on the
; screen.
cursor_show:
        SAVE r8-r12
        MOV  [cur_x], r1
        MOV  [cur_y], r2
        MOV  r5, r1
        AND  r5, #7
        LSL  r5, #2             ; r5: s
        ASR  r1, #3
        LSL  r1, #2
        MOV  r0, r2             ; r2: the first row's first word
        LSL  r0, #8
        LSL  r2, #6
        ADD  r2, r0
        ADD  r2, r1
        ADD  r2, #fb
        MOV  [under_at], r2
        MOV  r3, r2             ; save under
        MOV  r4, #under
        MOV  r6, #16
.save:  MOV  r0, [r3]
        MOV  [r4]+, r0
        MOV  r0, [r3 + 4]
        MOV  [r4]+, r0
        MOV  r0, [r3 + 8]
        MOV  [r4]+, r0
        ADD  r3, #PITCH
        DBNZ r6, .save
        MOV  r3, #cursor_art    ; r3: the art, 4 words a row
        MOV  r6, #16
        TST  r5, r5
        BEQ  .al
        MOV  r4, #32
        SUB  r4, r5             ; r4: 32 - s
.row:   MOV  r8, [r3]           ; r8, r9: the image; r10, r11: the mask
        MOV  r9, [r3 + 4]
        MOV  r10, [r3 + 8]
        MOV  r11, [r3 + 12]
        ADD  r3, #16
        MOV  r0, r10            ; word 0
        LSL  r0, r5
        MOV  r1, r8
        LSL  r1, r5
        MOV  r12, [r2]
        BIC  r12, r0
        OR   r12, r1
        MOV  [r2], r12
        MOV  r0, r10            ; word 1
        LSR  r0, r4
        MOV  r12, r11
        LSL  r12, r5
        OR   r0, r12
        MOV  r1, r8
        LSR  r1, r4
        MOV  r12, r9
        LSL  r12, r5
        OR   r1, r12
        MOV  r12, [r2 + 4]
        BIC  r12, r0
        OR   r12, r1
        MOV  [r2 + 4], r12
        LSR  r11, r4            ; word 2
        LSR  r9, r4
        MOV  r12, [r2 + 8]
        BIC  r12, r11
        OR   r12, r9
        MOV  [r2 + 8], r12
        ADD  r2, #PITCH
        DEC  r6
        BNE  .row
        BRA  .done
.al:    MOV  r0, [r2]           ; on a word: two words a row
        BIC  r0, [r3 + 8]
        OR   r0, [r3]
        MOV  [r2], r0
        MOV  r0, [r2 + 4]
        BIC  r0, [r3 + 12]
        OR   r0, [r3 + 4]
        MOV  [r2 + 4], r0
        ADD  r3, #16
        ADD  r2, #PITCH
        DEC  r6
        BNE  .al
.done:  RESTORE r8-r12
        RET

; cursor_hide(): what was under the cursor put back
cursor_hide:
        MOV  r2, [under_at]
        MOV  r3, #under
        MOV  r1, #16
.row:   MOV  r0, [r3]+
        MOV  [r2], r0
        MOV  r0, [r3]+
        MOV  [r2 + 4], r0
        MOV  r0, [r3]+
        MOV  [r2 + 8], r0
        ADD  r2, #PITCH
        DBNZ r1, .row
        RET

; ---- data ------------------------------------------------------------------------------

        .data
        .align 4
optab:  .word 0, 0, op_move, op_scroll, op_raise, op_type, op_select
screen: .word 0, 0, SW, SH
nwin:   .word 0
nops:   .word 0
ops:    .word 0                 ; the next action
nlines: .word 0
cur_x:  .word 0
cur_y:  .word 0
under_at: .word 0               ; where the saved words came from
sel_new: .space 16

        .bss
        .align 4
wins:   .space W_SIZE * NWMAX
order:  .space 4 * NWMAX        ; the windows, back to front
lines:  .space 8 * MAXLINES     ; the corpus's lines: address, length
rl_a:   .space 16 * MAXRECTS    ; visible's two lists
rl_b:   .space 16 * MAXRECTS
exposed: .space 64              ; what a move uncovers
under:  .space 16 * 12          ; what's under the cursor
