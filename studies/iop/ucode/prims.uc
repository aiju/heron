; The IOP's microcode, part 3: the Forth's primitives (RFC 0027, 6.3),
; from 0x8000 on, after `pause` in core.uc. Each ends in NEXT, whose delay
; slot takes the primitive's last step when it has one. The top of the
; data stack is in AC; sp addresses the second item; the stacks grow down.
; t0-t7 are scratch. AC is tested for zero with m1, -1: m1 + AC carries
; unless AC is 0, and K stays free for the branch.

; ---- the inner interpreter's words

.prim exit
xexit:  X <- rp
        F <- [X] + 1 | X <- F   ; the caller's next cell
        ip <- F
        F <- [X] | X <- F | dispatch nest
        rp <- rp + 1

.prim lit
        sp, X <- sp - 1
        [X] <- AC
        ip, X <- ip + 1
        AC <- [X]
        NEXT

; branch and friends take the address of the cell to go on at, inline;
; they look at attention as they go.
.prim branch
xbranch: ip, X <- ip + 1
        F <- [X] - 1 | if attn goto attn_next
        ip <- F
        NEXT

.prim 0branch
        F <- m1 + AC | if carry goto zb_no     ; not zero: don't branch
        X <- sp
        AC <- [X]
        sp <- sp + 1
        ip, X <- ip + 1
        F <- [X] - 1 | if attn goto attn_next
        ip <- F
        NEXT
zb_no:  AC <- [X] | if attn goto zb_attn
        sp <- sp + 1
        ip <- ip + 1
        NEXT
zb_attn: ip <- ip + 1 | goto attn_next
        nop

; execute: a primitive is jumped to, and ends with its own NEXT, as ip
; hasn't moved; a colon definition goes through nest-w (core.uc).
.prim execute
        w <- AC
        X <- sp
        AC <- [X]
        F <- w | dispatch nestw
        sp <- sp + 1

; Loops keep the limit and index - limit on the return stack, so that the
; index reaching the limit is a carry out of index - limit.
.prim (do)                      ; ( limit index -- )
xdo:    X <- sp
        F <- [X]
        t0 <- F
        AC <- [X] - AC
        AC <- (#0 | ~AC) + 1
        rp, X <- rp - 1
        F <- t0
        [X] <- F
        rp, X <- rp - 1
        [X] <- AC
        sp, X <- sp + 1
        AC <- [X]
        NEXT | sp <- sp + 1

.prim (?do)                     ; ( limit index -- ) past the loop if they're equal
        X <- sp
        F <- [X] ^ AC | swap <- F
        F <- swap - 1 | if carry goto qdo_go
        nop
        sp, X <- sp + 1
        AC <- [X]
        sp <- sp + 1 | goto xbranch
        nop
qdo_go: ip <- ip + 1 | goto xdo         ; over the operand
        nop

.prim (loop)
        X <- rp
        [X] <- [X] + 1 | if carry goto loop_end
        ip, X <- ip + 1
        F <- [X] - 1 | if attn goto attn_next
        ip <- F
        NEXT
loop_end: rp <- rp + 1
        NEXT | rp <- rp + 1

; ( n -- ) Ends when the index crosses from limit - 1 to limit: a carry
; out for n >= 0, none for n < 0.
.prim (+loop)
        X <- rp
        F <- AC | if F15 goto pl_neg
        [X] <- [X] + AC
        if carry goto pl_end
        nop
pl_go:  X <- sp
        AC <- [X]
        sp <- sp + 1
        ip, X <- ip + 1
        F <- [X] - 1 | if attn goto attn_next
        ip <- F
        NEXT
pl_neg: if carry goto pl_go
        nop
pl_end: X <- sp
        AC <- [X]
        sp <- sp + 1
        rp <- rp + 1
        ip <- ip + 1
        NEXT | rp <- rp + 1

.prim i
        sp, X <- sp - 1
        [X] <- AC
        X <- rp
        AC <- [X]
        F <- rp + 1 | X <- F
        AC <- [X] + AC
        NEXT

.prim j
        sp, X <- sp - 1
        [X] <- AC
        F <- rp + 1
        t0 <- F
        t0, X <- t0 + 1
        AC <- [X]
        t0, X <- t0 + 1
        AC <- [X] + AC
        NEXT

.prim unloop
        rp <- rp + 1
        NEXT | rp <- rp + 1

; ---- the stacks

.prim dup
        sp, X <- sp - 1
        [X] <- AC
        NEXT

.prim ?dup
        F <- m1 + AC | ifnot carry goto next
        nop
        sp, X <- sp - 1
        [X] <- AC
        NEXT

.prim drop
        X <- sp
        AC <- [X]
        NEXT | sp <- sp + 1

.prim swap
        X <- sp
        [X] <- [X] ^ AC
        AC <- [X] ^ AC
        [X] <- [X] ^ AC
        NEXT

.prim over
        sp, X <- sp - 1
        [X] <- AC
        F <- sp + 1 | X <- F
        AC <- [X]
        NEXT

.prim nip
        NEXT | sp <- sp + 1

.prim rot                       ; ( a b c -- b c a )
        X <- sp
        F <- [X]
        t0 <- F
        [X] <- AC
        F <- sp + 1 | X <- F
        AC <- [X]
        F <- t0
        [X] <- F
        NEXT

.prim 2dup
        X <- sp
        F <- [X]
        t0 <- F
        sp, X <- sp - 1
        [X] <- AC
        sp, X <- sp - 1
        F <- t0
        [X] <- F
        NEXT

.prim 2drop
        F <- sp + 1 | X <- F
        AC <- [X]
        sp <- sp + 1
        NEXT | sp <- sp + 1

.prim >r
        rp, X <- rp - 1
        [X] <- AC
        X <- sp
        AC <- [X]
        NEXT | sp <- sp + 1

.prim r>
        sp, X <- sp - 1
        [X] <- AC
        X <- rp
        AC <- [X]
        NEXT | rp <- rp + 1

.prim r@
        sp, X <- sp - 1
        [X] <- AC
        X <- rp
        AC <- [X]
        NEXT

.prim rdrop
        NEXT | rp <- rp + 1

.prim sp@                       ; ( -- a ) sp before the push: s0 - sp@ is the depth
        sp, X <- sp - 1
        [X] <- AC
        AC <- sp + 1
        NEXT

.prim sp!                       ; ( a -- ) the stack empty at a
        sp <- AC
        NEXT

.prim rp@
        sp, X <- sp - 1
        [X] <- AC
        AC <- rp
        NEXT

.prim rp!
        rp <- AC
        X <- sp
        AC <- [X]
        NEXT | sp <- sp + 1

.prim up@                       ; ( -- a ) the task's register 0: its user area
        sp, X <- sp - 1
        [X] <- AC
        AC <- up
        NEXT

.prim (user)                    ; ( -- a ) up plus the offset inline
        sp, X <- sp - 1
        [X] <- AC
        ip, X <- ip + 1
        AC <- up
        AC <- [X] + AC
        NEXT

; ---- arithmetic and logic

.prim +
        X <- sp
        AC <- [X] + AC
        NEXT | sp <- sp + 1

.prim -
        X <- sp
        AC <- [X] - AC
        NEXT | sp <- sp + 1

.prim and
        X <- sp
        AC <- [X] & AC
        NEXT | sp <- sp + 1

.prim or
        X <- sp
        AC <- [X] | AC
        NEXT | sp <- sp + 1

.prim xor
        X <- sp
        AC <- [X] ^ AC
        NEXT | sp <- sp + 1

.prim invert
        AC <- ~AC
        NEXT

.prim negate
        AC <- (#0 | ~AC) + 1
        NEXT

.prim 1+
        AC <- #1 + AC
        NEXT

.prim 1-
        AC <- #-1 + AC
        NEXT

.prim 2*
        t0 <- AC
        AC <- t0 + AC
        NEXT

.prim lshift                    ; ( x n -- x' )
        t1 <- AC
        X <- sp
        AC <- [X]
        sp <- sp + 1
ls_loop: t1 <- t1 - 1 | ifnot carry goto next
        t0 <- AC
        AC <- t0 + AC | goto ls_loop
        nop

; ( x n -- x' ) No right shift in the datapath: rotate left 16 - n times
; (x + x, and the bit that falls out back in at the bottom) and keep the
; low 16 - n bits.
.prim rshift
        t1 <- AC
        X <- sp
        AC <- [X]
        t0 <- AC
        sp <- sp + 1
        F <- t1 - 1 | ifnot carry goto rs_none
        AC <- #16
        F <- t1 - AC | if carry goto ret_false  ; n >= 16
        AC <- t1 - AC
        t1 <- (#0 | ~AC) + 1    ; 16 - n
        t2 <- #1
rs_loop: t1 <- t1 - 1 | ifnot carry goto rs_end
        nop
        t0 <- t0 + t0 | ifnot carry goto rs_loop
        t2 <- t2 + t2
        t0 <- t0 + 1 | goto rs_loop
        nop
rs_end: AC <- t2 - 1
        AC <- t0 & AC
        NEXT
rs_none: AC <- t0
        NEXT

; ( u1 u2 -- ud ) 16 steps of shift and add, the product shifted left.
.prim um*
        t2 <- AC
        X <- sp
        AC <- [X]
        t0 <- #0
        t1 <- #0
        LC <- #0
um_loop: t0 <- t0 + t0 | ifnot carry goto um_1
        t1 <- t1 + t1
        t1 <- t1 + 1
um_1:   t2 <- t2 + t2 | ifnot carry goto um_2
        nop
        t0 <- t0 + AC | ifnot carry goto um_2
        nop
        t1 <- t1 + 1
um_2:   if lc goto um_loop
        nop
        F <- t0
        [X] <- F
        AC <- t1
        NEXT

; ( ud u -- rem quot ) 16 steps of restoring division.
.prim um/mod
        t2 <- AC
        X <- sp
        AC <- [X]
        t1 <- AC                ; the dividend's high half
        F <- sp + 1 | X <- F
        AC <- [X]
        t0 <- AC                ; its low half
        AC <- t2
        LC <- #0
dv_loop: t1 <- t1 + t1 | if carry goto dv_big
        nop
        t0 <- t0 + t0 | ifnot carry goto dv_cmp
        nop
        t1 <- t1 + 1
dv_cmp: F <- t1 - AC | ifnot carry goto dv_next
        nop
dv_sub: t1 <- t1 - AC
        t0 <- t0 + 1
dv_next: if lc goto dv_loop
        nop
        F <- t1
        [X] <- F
        AC <- t0
        NEXT | sp <- sp + 1
dv_big: t0 <- t0 + t0 | ifnot carry goto dv_sub
        nop
        t1 <- t1 + 1 | goto dv_sub
        nop

.prim swab                      ; ( x -- x' ) its bytes swapped
        F <- AC | swap <- F
        AC <- swap
        NEXT

; ---- comparisons: true is -1

.prim =
        X <- sp
        AC <- [X] ^ AC
        F <- m1 + AC | ifnot carry goto ret_true
        sp <- sp + 1
        AC <- #0
        NEXT

.prim <>
        X <- sp
        AC <- [X] ^ AC
        F <- m1 + AC | if carry goto ret_true
        sp <- sp + 1
        AC <- #0
        NEXT

.prim 0=
        F <- m1 + AC | ifnot carry goto ret_true
        AC <- #0
        NEXT

.prim 0<>
        F <- m1 + AC | if carry goto ret_true
        AC <- #0
        NEXT

.prim 0<
        F <- AC | if F15 goto ret_true
        AC <- #0
        NEXT

.prim u<
        X <- sp
        F <- [X] - AC | ifnot carry goto ret_true
        sp <- sp + 1
        AC <- #0
        NEXT

; Signs that differ decide by themselves; the same signs by the
; difference's.
.prim <
        X <- sp
        F <- [X] ^ AC | if F15 goto lt_signs
        sp <- sp + 1
        F <- [X] - AC | if F15 goto ret_true
        AC <- #0
        NEXT
lt_signs: F <- [X] | if F15 goto ret_true
        AC <- #0
        NEXT

; ---- memory

.prim @
        X <- AC
        AC <- [X]
        NEXT

.prim !                         ; ( x a -- )
        t0 <- AC
        X <- sp
        AC <- [X]
        X <- t0
        [X] <- AC
        sp, X <- sp + 1
        AC <- [X]
        NEXT | sp <- sp + 1

.prim +!                        ; ( n a -- )
        t0 <- AC
        X <- sp
        AC <- [X]
        X <- t0
        [X] <- [X] + AC
        sp, X <- sp + 1
        AC <- [X]
        NEXT | sp <- sp + 1

; ---- the dictionary (kernel.fs): a header is its link, its flags (bits
; 0-5 the name's length, 13 smudged) and its name, a character a cell

; ( c-addr h -- h' | 0 ) From header h along the links, the first whose
; name is the counted string at c-addr, case aside, and isn't smudged.
; t0 c-addr, t1 its length, t2 the flags' mask, t3 the header; AC holds
; the length while the scan goes, which compares it with the flags as
; (flags ^ length) & mask. It yields to attention at each header, to
; come back to that one: ip back a cell, ( c-addr h' ).
.prim (search)
        t3 <- AC
        X <- sp
        F <- [X] | X <- F
        t0 <- F
        AC <- [X]
        t1 <- AC
        AC <- #0x203F
        t2 <- AC
        AC <- t1
        F <- t3 - 1 | ifnot carry goto sr_none  ; h = 0
        X <- t3 + 1
sr_flags: AC <- [X] ^ AC
        F <- (t2 & AC) - 1 | ifnot carry goto sr_cand
        AC <- [X] ^ AC                          ; (delay) the length again
        X <- t3
sr_link: F <- [X] - 1 | ifnot carry goto sr_none
        t3 <- F
        t3 <- t3 + 1 | ifnot attn goto sr_flags
        X <- t3 + 1
        AC <- t3 | goto attn_next
        ip <- ip - 1
sr_none: AC <- #0
        NEXT | sp <- sp + 1
; the name, a character at a time: t5 the header's, t6 the string's, t7
; the characters left less one
sr_cand: AC <- t3
        t5 <- #2 + AC
        AC <- t1
        t7 <- #0xFFFF + AC
        AC <- t0
        t6, X <- #1 + AC
sr_cmp: AC <- [X]
        X <- t5
        AC <- [X] ^ AC
        F <- m1 + AC | if carry goto sr_fold
        t5 <- t5 + 1
sr_ok:  t6, X <- t6 + 1
        t7 <- t7 - 1 | if carry goto sr_cmp
        AC <- t3                                ; (delay) found
        NEXT | sp <- sp + 1
; they differ: the same letter in the other case, or not the name
sr_fold: AC <- #0x20 ^ AC
        F <- m1 + AC | if carry goto sr_next
        AC <- [X]                               ; (delay) the header's character
        AC <- #0x20 | AC
        AC <- #(0x10000 - 0x61) + AC
        AC <- #(0x10000 - 26) + AC              ; carries unless a to z
        ifnot carry goto sr_ok
        nop
sr_next: AC <- t1 | goto sr_link
        X <- t3

; ---- the system bus: addresses as double cells ( lo hi ), halfwords
; and bytes. Each takes the bus for its transfer and lets it go.

.prim bus@                      ; ( lo hi -- x )
        AH0 <- AC
        CTRL <- #(8 | CTRL_SESSION)
        X <- sp
        F <- [X] | rd.h AH0
        sp <- sp + 1
        AC <- BA
        CTRL <- #CTRL_SESSION
        NEXT

.prim bus!                      ; ( x lo hi -- )
        AH0 <- AC
        CTRL <- #(8 | CTRL_SESSION)
        F <- sp + 1 | X <- F
        F <- [X] | AB <- F
        X <- sp
        F <- [X] | wr.h AH0
        CTRL <- #CTRL_SESSION
        sp <- sp + 1
        sp, X <- sp + 1
        AC <- [X]
        NEXT | sp <- sp + 1

; A byte at an odd address is on D8-D15: the swap register brings it down,
; or takes it up.
.prim busc@                     ; ( lo hi -- c )
        AH0 <- AC
        CTRL <- #(8 | CTRL_SESSION)
        AC <- #1
        X <- sp
        F <- ([X] & AC) - 1 | if carry goto bcr_odd
        sp <- sp + 1
        F <- [X] | rd.b0 AH0
        CTRL <- #CTRL_SESSION
        AC <- #0xFF
        AC <- BA & AC
        NEXT
bcr_odd: F <- [X] | rd.b1 AH0
        CTRL <- #CTRL_SESSION
        F <- BA | swap <- F
        AC <- #0xFF
        AC <- swap & AC
        NEXT

.prim busc!                     ; ( c lo hi -- )
        AH0 <- AC
        CTRL <- #(8 | CTRL_SESSION)
        AC <- #1
        X <- sp
        F <- ([X] & AC) - 1 | if carry goto bcw_odd
        F <- sp + 1 | X <- F
        F <- [X] | AB <- F
        X <- sp
        F <- [X] | wr.b0 AH0
        goto bcw_end
        nop
bcw_odd: F <- [X] | swap <- F
        AB <- swap
        X <- sp
        F <- [X] | wr.b1 AH0
bcw_end: CTRL <- #CTRL_SESSION
        sp <- sp + 1
        sp, X <- sp + 1
        AC <- [X]
        NEXT | sp <- sp + 1

; ---- the I/O bus, by 256 x device + register

.prim io@                       ; ( a -- x )
        X <- AC
        AC <- io
        NEXT

.prim io!                       ; ( x a -- )
        t0 <- AC
        X <- sp
        AC <- [X]
        X <- t0
        F <- AC | io <- F
        sp, X <- sp + 1
        AC <- [X]
        NEXT | sp <- sp + 1

; ---- the shared RAM, by byte offset ( lo hi ): X takes the low half, its
; bit 0 ignored, and the page register the high

.prim sr@                       ; ( lo hi -- x )
        F <- AC | pg0 <- F
        X <- sp
        F <- [X] | X <- F
        AC <- sr
        NEXT | sp <- sp + 1

.prim sr!                       ; ( x lo hi -- )
        F <- AC | pg0 <- F
        F <- sp + 1 | X <- F
        AC <- [X]
        X <- sp
        F <- [X] | X <- F
        F <- AC | sr <- F
        sp <- sp + 1
        sp, X <- sp + 1
        AC <- [X]
        NEXT | sp <- sp + 1

; ---- the image flash, by ( register page ): 256 halfwords a page

.prim flash@                    ; ( reg page -- x )
        F <- AC | pg1 <- F
        X <- sp
        AC <- #(DEV_FLASH << 8)
        F <- [X] | AC | X <- F
        AC <- io
        NEXT | sp <- sp + 1

.prim flash!                    ; ( x reg page -- ) one write cycle
        F <- AC | pg1 <- F
        F <- sp + 1 | X <- F
        AC <- [X]
        t0 <- AC
        X <- sp
        AC <- #(DEV_FLASH << 8)
        F <- [X] | AC | X <- F
        AC <- t0
        F <- AC | io <- F
        sp <- sp + 1
        sp, X <- sp + 1
        AC <- [X]
        NEXT | sp <- sp + 1

; ( reg page -- reg' page' x ) a halfword from the image flash, and on
.prim (fl@+)
        t4 <- AC
        X <- sp
        AC <- #256
        F <- [X] - AC | ifnot carry goto fa_in
        nop
        t4 <- t4 + 1            ; past the page's end: the next
        [X] <- 0
fa_in:  F <- t4
        pg1 <- F
        AC <- #(DEV_FLASH << 8)
        F <- [X] | AC | X <- F
        AC <- io
        t5 <- AC
        X <- sp
        [X] <- [X] + 1
        sp, X <- sp - 1
        F <- t4
        [X] <- F
        AC <- t5
        NEXT

; ---- native jobs (RFC 0027, 6.4): a block moves in a pool job (jobs.uc),
; while the task that started it waits

; ( alo ahi blo bhi len start -- ) a <- b, len bytes, in a job that begins
; at start (js_copy, js_fill, ...); the task waits until it's done. With
; no bank free, it pauses and tries again.
.prim (job)
        X <- #JFREE
        F <- [X] - 1 | ifnot carry goto job_full
        F <- [X]
        t6 <- F                 ; the job's register 0
        t0 <- AC                ; the job's start
        X <- sp
        F <- [X]
        t1 <- F                 ; len
        sp, X <- sp + 1
        F <- [X]
        t2 <- F                 ; bhi
        sp, X <- sp + 1
        F <- [X]
        t3 <- F                 ; blo
        sp, X <- sp + 1
        F <- [X]
        t4 <- F                 ; ahi
        sp, X <- sp + 1
        F <- [X]
        t5 <- F                 ; alo
        sp, X <- sp + 1
        AC <- [X]
        tos <- AC               ; the new top, for pause
        sp <- sp + 1
        AC <- up
        F <- #wait + AC
        t7 <- F                 ; the task's wait register
        AC <- t6
        X <- #jres + AC
        F <- t0
        [X] <- F
        X <- #jkind + AC
        F <- [X]
        t0 <- F
        X <- #JFREE
        F <- t0
        [X] <- F                ; out of the free list
        X <- #jkind + AC
        F <- #JK_WAKE
        [X] <- F
        X <- #jarg + AC
        F <- t7
        [X] <- F
        X <- #jleft + AC
        F <- t1
        [X] <- F
        X <- #jbhi + AC
        F <- t2
        [X] <- F
        X <- #jblo + AC
        F <- t3
        [X] <- F
        X <- #jahi + AC
        F <- t4
        [X] <- F
        X <- #jalo + AC
        F <- t5
        [X] <- F
        X <- #jend + AC
        F <- #jfin
        [X] <- F
        X <- #jme + AC
        AC <- [X]
        wait <- #1              ; until the job is done
        t7 <- #job_q
        goto jenq
        nop
job_q:  CTRL <- #(8 | CTRL_WORK)
        goto pause1
        nop
job_full: ip <- ip - 1 | goto xpause
        nop

; ( src -- ) source src's event to its owner (jobs.uc's post)
.prim (post)
        t0 <- AC
        X <- sp
        AC <- [X]
        tos <- AC
        sp <- sp + 1
        goto post
        t7 <- #prim_ret
prim_ret: AC <- tos
        NEXT

; ( tag status rlo rhi settings -- ) a completion into a client's ring
; (jobs.uc's cpost)
.prim (complete)
        t0 <- AC
        X <- sp
        F <- [X]
        t4 <- F
        sp, X <- sp + 1
        F <- [X]
        t3 <- F
        sp, X <- sp + 1
        F <- [X]
        t2 <- F
        sp, X <- sp + 1
        F <- [X]
        t1 <- F
        sp, X <- sp + 1
        AC <- [X]
        tos <- AC
        sp <- sp + 1
        goto cpost
        t7 <- #prim_ret

; ( bank -- ) a job queued, if it isn't, and WORK on: a ring job, once its
; ring is set up
.prim (enqueue)
        X <- #JLINK + AC
        F <- [X] - 1 | if carry goto enq_done
        nop
        t7 <- #enq_done
        goto jenq
        nop
enq_done: CTRL <- #(8 | CTRL_WORK)
        X <- sp
        AC <- [X]
        NEXT | sp <- sp + 1

; ---- the rest

.prim ints@                     ; ( -- x ) the INT lines
        sp, X <- sp - 1
        [X] <- AC
        AC <- ev0
        NEXT

.prim stuck@                    ; ( -- x ) the stuck-transfer counter's STUCK and OWN, WAIT's bound's IOTO and device, then cleared
        sp, X <- sp - 1
        [X] <- AC
        AC <- #0x7F00
        AC <- ev1 & AC
        F <- #0 | ev3 <- F
        NEXT

.prim ttab!                     ; ( entry dev -- ) the timing table's entry for an I/O bus device
        F <- AC | swap <- F
        AC <- swap              ; dev << 8
        t0 <- AC
        X <- sp
        AC <- [X]
        X <- t0
        F <- AC | ttab <- F
        sp, X <- sp + 1
        AC <- [X]
        NEXT | sp <- sp + 1

.prim ctrl!                     ; ( x -- ) bit x[2:0] of CTRL to x[3]
        CTRL <- AC
        X <- sp
        AC <- [X]
        NEXT | sp <- sp + 1

.prim bye                       ; stops the microcode: for tests
bye:    goto bye
        nop
