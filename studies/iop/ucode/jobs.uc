; The IOP's microcode, part 2: the native jobs (RFC 0027, 6.4-6.5 and 7):
; posting events and completions to the CPUs, the movers, the Forth's jobs
; and the clients' ring jobs. A job runs in its own bank (layout.py has
; its registers) from jres, a slice at a time; between slices it looks at
; attention, and goes to jattn when there is some. jstop takes it out of
; the queue.

; ---- an event to a CPU (RFC 0027, 7.3; RFC 0037, 8): into the CPU's
; ring of events if it has one, then its level: a fast level's mailbox
; first and its bit at once; a slow level's bit at once, or held back
; until TICKS runs out. t0 the event (a source's number), t1 16 x the CPU,
; t2 the level, t3 the hold in ticks; t4-t6 scratch; back to t7. The ring
; and its block share a 64 KB page of the shared RAM.

post:   AC <- t1
        X <- #(EVRING + E_ON) + AC
        F <- [X] - 1 | ifnot carry goto po_level   ; no ring of events
        X <- #(EVRING + E_BLK + 1) + AC
        F <- [X] | pg0 <- F
        X <- #(EVRING + E_BLK) + AC
        AC <- [X]
        t5 <- AC                ; the block
        F <- #B_TAIL + AC | X <- F
        AC <- sr
        t6 <- AC                ; the CPU's tail
        AC <- t1
        X <- #(EVRING + E_MASK) + AC
        AC <- [X]
        t4 <- AC
        AC <- t1
        X <- #(EVRING + E_HEAD) + AC
        AC <- #2
        AC <- [X] + AC
        AC <- t4 & AC
        t4 <- AC                ; the head after this one
        AC <- t6 ^ AC
        F <- m1 + AC | ifnot carry goto po_full    ; that's the CPU's tail: full
        AC <- [X]
        F <- t4
        [X] <- F
        t6 <- AC                ; this one
        AC <- t1
        X <- #(EVRING + E_RING) + AC
        AC <- [X]
        F <- t6 + AC | X <- F
        F <- t0 | sr <- F       ; the event
        F <- t5 | X <- F
        F <- t4 | sr <- F       ; and the head, published
po_level: AC <- t2
        X <- #LEVELBIT + AC
        F <- [X]
        t4 <- F                 ; the level's bit
        AC <- #FAST_LEVEL
        F <- t2 - AC | if carry goto po_fast
        nop
        F <- t3 - 1 | ifnot carry goto po_now      ; not held
        AC <- t1
        X <- #(EVRING + E_PEND) + AC
        AC <- t4
        [X] <- [X] | AC         ; held: it goes when TICKS runs out
        X <- #TICKS
        AC <- t3
        F <- [X] - AC | ifnot carry goto po_ret    ; that's sooner already
        nop
        [X] <- AC
po_ret: F <- t7 | goto F
        nop
po_full: F <- t5 | X <- F       ; dropped, and counted in the block
        AC <- #B_DROP
        F <- t5 + AC | X <- F
        AC <- sr
        F <- #1 + AC | sr <- F
        goto po_level
        nop
po_fast: AC <- t1               ; the mailbox, if there's a block
        X <- #(EVRING + E_ON) + AC
        F <- [X] - 1 | ifnot carry goto po_now
        X <- #(EVRING + E_BLK + 1) + AC
        F <- [X] | pg0 <- F
        X <- #(EVRING + E_BLK) + AC
        AC <- [X]
        t5 <- AC
        AC <- t2
        AC <- t2 + AC
        AC <- t5 + AC
        F <- #(B_MAIL - 2 * FAST_LEVEL) + AC | X <- F
        F <- t0 | sr <- F
po_now: AC <- t1                ; the bit, on the bus
        X <- #(EVRING + E_SEG) + AC
        AH0 <- [X]
        CTRL <- #(8 | CTRL_SESSION)
        F <- t4 | AB <- F
        F <- #IRQ_SET | wr.h AH0
        CTRL <- #CTRL_SESSION
        F <- t7 | goto F
        nop

; ---- a completion into a client's ring (RFC 0027, 7.1): t0 its settings
; (RINGS + 32c), t1 the tag, t2 the status, t3-t4 the result; t5-t6
; scratch; back to t7. The rings and their indices share a 64 KB page of
; the shared RAM. A full ring drops it, and counts it in DROPPED.

cpost:  AC <- t0
        X <- #(R_CMP + 1) + AC
        F <- [X] | pg0 <- F
        X <- #R_IDX + AC
        AC <- [X]
        F <- #I_CMPTAIL + AC | X <- F
        AC <- sr
        t6 <- AC                ; the client's tail
        AC <- t0
        X <- #R_CMASK + AC
        AC <- [X]
        t5 <- AC
        AC <- t0
        X <- #R_CHEAD + AC
        AC <- #8
        AC <- [X] + AC
        AC <- t5 & AC
        t5 <- AC                ; the head after this one
        AC <- t6 ^ AC
        F <- m1 + AC | ifnot carry goto cp_full
        AC <- [X]
        F <- t5
        [X] <- F
        t6 <- AC                ; this one
        AC <- t0
        X <- #R_CMP + AC
        AC <- [X]
        F <- t6 + AC | X <- F
        t6 <- F
        F <- t1 | sr <- F       ; the tag
        AC <- #2
        t6, X <- t6 + AC
        F <- t2 | sr <- F       ; the status
        t6, X <- t6 + AC
        F <- t3 | sr <- F       ; the result
        t6, X <- t6 + AC
        F <- t4 | sr <- F
        AC <- t0
        X <- #R_IDX + AC
        AC <- [X]
        F <- #I_CMPHEAD + AC | X <- F
        F <- t5 | sr <- F       ; published
        F <- t7 | goto F
        nop
cp_full: X <- #DROPPED
        [X] <- [X] + 1
        F <- t7 | goto F
        nop

; ---- the movers (RFC 0027, 11.2): a <- b, jleft bytes, in chunks that
; keep each address within its 64 KB (b within its page of the image
; flash), and the chunks in slices of at most 16 bus transfers, each a
; session on the bus, with a look at attention between them. A mover's
; start (jmv) takes its pointers from a and b and sets jres to its entry,
; which loads the segments and pages: the native layer may have changed
; them between slices. At a chunk's end it puts its pointers back in a
; and b.
;
; Halfwords only: addresses and lengths even, and for the devices'
; movers (ib, bi) multiples of 4.

; A slice: TOP, the mover's go line and loop, TAIL, LAST. S is a full
; slice's bytes, full LC for it; on and off what CTRL does around it. sl
; takes a slice's bytes off jchunk and goes to last when there isn't a
; whole slice left; last does what is, or ends the chunk.
.macro TOP name S full on
\name_top: AC <- #\S
\name_sl: jchunk <- jchunk - AC | ifnot carry goto \name_last
        \on
        LC <- #\full
.endm

; Attention between slices: the tick alone is counted and cleared here,
; and the job goes on at back with AC set to ac; anything else is the
; native layer's (jattn).
.macro TICK back ac
        F <- ev1 | ifnot F15 goto jattn            ; not the tick: a doorbell
        X <- #TICKS
        F <- ev1 - 1 | if F15 goto jattn           ; an ATN line too
        F <- ev0 - 1
        if carry goto jattn                         ; an INT line
        AC <- #(TURN_TICKS - 1)
        [X] <- [X] - 1 | ifnot carry goto jattn_t   ; held levels are due
        F <- ([X] & AC) - 1
        ifnot carry goto jattn_t                    ; the turn is over
        AC <- #\ac
        ev1 <- F | goto \back
        nop
.endm

.macro TAIL name S off
        \off
        ifnot attn goto \name_sl
        AC <- #\S
        TICK \name_sl \S
.endm

; jchunk is less than a slice now, S less what's left.
.macro LAST name tab S off
\name_last: AC <- jchunk
        AC <- #\S + AC
        F <- m1 + AC | ifnot carry goto \name_e0
        X <- #\tab + AC
        LC <- [X] | goto \name_go
        jchunk <- 0
\name_e0: \off
.endm

mv_start: F <- jleft - 1 | ifnot carry goto mv_done     ; nothing to move

; The next chunk: what's left, but no further than a boundary.
mv_chunk: AC <- jleft
        jchunk <- AC
        AC <- jalo
        AC <- (#0 | ~AC) + 1    ; to a's 64 KB boundary, 0 for 64 KB
        F <- m1 + AC | ifnot carry goto mc_b
        F <- jchunk - AC
        ifnot carry goto mc_b
        nop
        jchunk <- AC
mc_b:   F <- jbk | if F15 goto mc_end   ; b isn't an address
        F <- jbk - 1
        if carry goto mc_fl     ; b is in the image flash
        AC <- jblo
        AC <- (#0 | ~AC) + 1
        F <- m1 + AC | ifnot carry goto mc_end
        F <- jchunk - AC
        ifnot carry goto mc_end
        nop
        jchunk <- AC | goto mc_end
        nop
mc_fl:  AC <- #256 - AC         ; halfwords to the page's end
        jt <- AC
        AC <- jt + AC
        F <- jchunk - AC | ifnot carry goto mc_end
        nop
        jchunk <- AC
mc_end: AC <- jchunk
        jleft <- jleft - AC
        F <- jmv | goto F
        nop

; A chunk is done: the next, with a's and b's high halves carried.
mv_next: F <- jleft - 1 | ifnot carry goto mv_done
        AC <- jalo
        F <- m1 + AC | if carry goto mn_b
        nop
        jahi <- jahi + 1
mn_b:   F <- jbk | if F15 goto mv_chunk
        AC <- jblo
        F <- jbk - 1 | if carry goto mn_fl
        nop
        F <- m1 + AC | if carry goto mv_chunk
        nop
        jbhi <- jbhi + 1 | goto mv_chunk
        nop
mn_fl:  AC <- #256 ^ AC
        F <- m1 + AC | if carry goto mv_chunk
        nop
        jblo <- 0
        jbhi <- jbhi + 1 | goto mv_chunk
        nop
mv_done: F <- jend | goto F
        nop

; bus to bus: a read and a write a halfword, 8 a slice
mv_bb:  F <- jalo
        jp <- F
        F <- jblo
        jp2 <- F
        jres <- #bb_in
bb_in:  AH0 <- jbhi
        AH1 <- jahi
        TOP bb 16 8 CTRL<-json
bb_go:  AC <- #2
bb_loop: jp2 <- jp2 + AC | rd.h AH0 | if lc goto bb_loop
        jp <- jp + AC | AB <- BA | wr.h AH1
        TAIL bb 16 CTRL<-jsoff
        LAST bb NEGHALF 16 CTRL<-jsoff
bb_end: F <- jp
        jalo <- F
        F <- jp2
        jblo <- F | goto mv_next
        nop

; the shared RAM to the bus: its side is local, so a halfword is one
; transfer (RFC 0027, 4.3)
mv_bs:  F <- jalo
        jsb <- F
        F <- jblo
        jsx <- F
        jres <- #bs_in
bs_in:  F <- jbhi
        pg0 <- F
        AH1 <- jahi
        TOP bs 32 0 CTRL<-json
bs_go:  AC <- #2
        X <- jsx
bs_loop: jsb <- jsb + AC | AB <- sr | wr.h AH1 | if lc goto bs_loop
        jsx, X <- jsx + AC
        TAIL bs 32 CTRL<-jsoff
        LAST bs NEGHALF 32 CTRL<-jsoff
bs_end: F <- jsb
        jalo <- F
        F <- jsx
        jblo <- F | goto mv_next
        nop

; the bus to the shared RAM
mv_sb:  F <- jalo
        jsx <- F
        F <- jblo
        jp2 <- F
        jres <- #sb_in
sb_in:  F <- jahi
        pg0 <- F
        AH0 <- jbhi
        TOP sb 32 0 CTRL<-json
sb_go:  AC <- #2
        X <- jsx
sb_loop: jp2 <- jp2 + AC | rd.h AH0 | if lc goto sb_loop
        jsx, X <- jsx + AC | sr <- BA
        TAIL sb 32 CTRL<-jsoff
        LAST sb NEGHALF 32 CTRL<-jsoff
sb_end: F <- jsx
        jalo <- F
        F <- jp2
        jblo <- F | goto mv_next
        nop

; within the shared RAM: X and the page for each side, a halfword at a
; time
mv_ss:  F <- jalo
        jsx <- F
        F <- jblo
        jp2 <- F
        jres <- #ss_in
ss_in:  TOP ss 32 0 nop
ss_go:  AC <- #2
ss_loop: F <- jbhi
        pg0 <- F
        X <- jp2
        jq2 <- sr
        F <- jahi
        pg0 <- F
        X <- jsx
        F <- jq2 | sr <- F
        jp2 <- jp2 + AC | if lc goto ss_loop
        jsx <- jsx + AC
        TAIL ss 32 nop
        LAST ss NEGHALF 32 nop
ss_end: F <- jsx
        jalo <- F
        F <- jp2
        jblo <- F | goto mv_next
        nop

; a fill on the bus, from AB: two writes a pass, so that a write starts
; every microinstruction and waits only for the one before; an odd
; halfword first
mv_fb:  F <- jalo
        jp <- F
        jres <- #fb_in
fb_in:  AH1 <- jahi
        F <- jblo | AB <- F
        TOP fb 32 8 CTRL<-json
fb_go:  AC <- #2
fb_loop: jp <- jp + AC | wr.h AH1 | if lc goto fb_loop
        jp <- jp + AC | wr.h AH1
fb_tail: TAIL fb 32 CTRL<-jsoff
fb_last: AC <- jchunk
        AC <- #32 + AC          ; what's left: less than a slice
        F <- m1 + AC | ifnot carry goto fb_e0      ; nothing
        X <- #NEGQUART + AC
        jchunk <- AC
        AC <- #2 & AC
        F <- m1 + AC | ifnot carry goto fb_pairs   ; a multiple of 4
        LC <- [X]
        AC <- #2
        jp <- jp + AC | wr.h AH1                    ; the odd halfword
        AC <- #4
        F <- jchunk - AC | ifnot carry goto fb_one  ; that was all
        nop
fb_pairs: jchunk <- 0 | goto fb_go
        nop
fb_one: jchunk <- 0 | goto fb_tail
        nop
fb_e0:  CTRL <- jsoff
fb_end: F <- jp
        jalo <- F | goto mv_next
        nop

; a fill in the shared RAM, from jsb
mv_fs:  F <- jalo
        jsx <- F
        F <- jblo
        jsb <- F
        jres <- #fs_in
fs_in:  F <- jahi
        pg0 <- F
        TOP fs 32 0 nop
fs_go:  AC <- #2
        X <- jsx
fs_loop: F <- jsb | sr <- F | if lc goto fs_loop
        jsx, X <- jsx + AC
        TAIL fs 32 nop
        LAST fs NEGHALF 32 nop
fs_end: F <- jsx
        jalo <- F | goto mv_next
        nop

; the image flash to the bus: b is (halfword in its page, page)
mv_lb:  F <- jalo
        jp <- F
        AC <- jblo
        F <- #(DEV_FLASH << 8) + AC
        jx <- F
        jres <- #lb_in
lb_in:  F <- jbhi
        pg1 <- F
        AH1 <- jahi
        TOP lb 32 0 CTRL<-json
lb_go:  AC <- #2
        X <- jx
lb_loop: jp <- jp + AC | AB <- io | wr.h AH1 | if lc goto lb_loop
        jx, X <- jx + 1
        TAIL lb 32 CTRL<-jsoff
        LAST lb NEGHALF 32 CTRL<-jsoff
lb_end: F <- jp
        jalo <- F
        AC <- #(DEV_FLASH << 8)
        F <- jx - AC
        jblo <- F | goto mv_next
        nop

; a device's register (X = jx) to the bus: two halfwords a pass
mv_ib:  F <- jalo
        jp <- F
        F <- jblo
        jx <- F
        jres <- #ib_in
ib_in:  AH1 <- jahi
        TOP ib 32 8 CTRL<-json
ib_go:  AC <- #2
        X <- jx
ib_loop: jp <- jp + AC | AB <- io | wr.h AH1 | if lc goto ib_loop
        jp <- jp + AC | AB <- io | wr.h AH1
        TAIL ib 32 CTRL<-jsoff
        LAST ib NEGQUART 32 CTRL<-jsoff
ib_end: F <- jp
        jalo <- F | goto mv_next
        nop

; a device's register to the shared RAM: X takes turns, and the data waits
; in AC; jsx is a's address less one, as X ignores its bit 0
mv_is:  AC <- jalo
        F <- #-1 + AC
        jsx <- F
        F <- jblo
        jx <- F
        jres <- #is_in
is_in:  F <- jahi
        pg0 <- F
        TOP is 32 0 nop
is_go:  X <- jx
is_loop: AC <- io
        jsx, X <- jsx + 1
        F <- AC | sr <- F
        jsx <- jsx + 1 | if lc goto is_loop
        X <- jx
        TAIL is 32 nop
        LAST is NEGHALF 32 nop
is_end: AC <- jsx
        F <- #1 + AC
        jalo <- F | goto mv_next
        nop

; the bus to a device's register (a's low half is its X): two halfwords
; a pass
mv_bi:  F <- jalo
        jx <- F
        F <- jblo
        jp2 <- F
        jres <- #bi_in
bi_in:  AH0 <- jbhi
        TOP bi 32 8 CTRL<-json
bi_go:  AC <- #2
        X <- jx
bi_loop: jp2 <- jp2 + AC | rd.h AH0
        io <- BA
        jp2 <- jp2 + AC | rd.h AH0 | if lc goto bi_loop
        io <- BA
        TAIL bi 32 CTRL<-jsoff
        LAST bi NEGQUART 32 CTRL<-jsoff
bi_end: F <- jp2
        jblo <- F | goto mv_next
        nop

; the shared RAM to a device's register
mv_si:  F <- jalo
        jx <- F
        AC <- jblo
        F <- #-1 + AC
        jsx <- F
        jres <- #si_in
si_in:  F <- jbhi
        pg0 <- F
        TOP si 32 0 nop
si_go:
si_loop: jsx, X <- jsx + 1
        AC <- sr
        X <- jx
        F <- AC | io <- F | if lc goto si_loop
        jsx <- jsx + 1
        TAIL si 32 nop
        LAST si NEGHALF 32 nop
si_end: AC <- jsx
        F <- #1 + AC
        jblo <- F | goto mv_next
        nop

; ---- the Forth's jobs: `(job)` starts a pool job at one of these, with
; a, b and jleft set and jend at jfin. Region 4 is the shared RAM.

js_copy: jbk <- #B_ADDR
        AC <- #0xF000
        AC <- jahi & AC
        AC <- #0x4000 ^ AC
        F <- m1 + AC | ifnot carry goto jsc_a      ; a is in the shared RAM
        AC <- #0xF000
        AC <- jbhi & AC
        AC <- #0x4000 ^ AC
        F <- m1 + AC | ifnot carry goto jsc_bs
        nop
        goto mv_start
        jmv <- #mv_bb
jsc_bs: goto mv_start
        jmv <- #mv_bs
jsc_a:  AC <- jbhi & AC
        AC <- #0x4000 ^ AC
        F <- m1 + AC | ifnot carry goto jsc_ss
        nop
        goto mv_start
        jmv <- #mv_sb
jsc_ss: goto mv_start
        jmv <- #mv_ss

js_fill: jbk <- #B_NONE
        AC <- #0xF000
        AC <- jahi & AC
        AC <- #0x4000 ^ AC
        F <- m1 + AC | ifnot carry goto jsf_s
        nop
        goto mv_start
        jmv <- #mv_fb
jsf_s:  goto mv_start
        jmv <- #mv_fs

js_flash: jbk <- #B_FLASH
        goto mv_start
        jmv <- #mv_lb

js_fromio: jbk <- #B_NONE
        AC <- #0xF000
        AC <- jahi & AC
        AC <- #0x4000 ^ AC
        F <- m1 + AC | ifnot carry goto jsi_s
        nop
        goto mv_start
        jmv <- #mv_ib
jsi_s:  goto mv_start
        jmv <- #mv_is

js_toio: jbk <- #B_ADDR
        AC <- #0xF000
        AC <- jbhi & AC
        AC <- #0x4000 ^ AC
        F <- m1 + AC | ifnot carry goto jso_s
        nop
        goto mv_start
        jmv <- #mv_bi
jso_s:  goto mv_start
        jmv <- #mv_si

; A pool job's end: its task can run, its bank is free, and it leaves the
; queue.
jfin:   F <- jkind - 1 | ifnot carry goto jf_free
        X <- jarg
        [X] <- 0
        X <- #WOKE
        [X] <- -1
jf_free: X <- #JFREE
        F <- [X]
        jkind <- F
        F <- jbase
        [X] <- F
        goto jstop
        nop

; ---- a client's ring job (RFC 0027, 7.1-7.2), bank 64 + c: each request
; in turn, the fast ones (copy, fill, zero) here and the rest to the
; Forth's server, until the ring is empty. Its rings and indices share
; page jpg of the shared RAM.

jring:  F <- jpg | pg0 <- F
        X <- jidx               ; I_REQHEAD
        AC <- sr
        AC <- jrtail ^ AC
        F <- m1 + AC | ifnot carry goto jr_empty
        AC <- jrtail
        F <- jreq + AC | X <- F
        jt <- F
        AC <- #2
        jq0 <- sr               ; the request, into jq0-jq7
        jt, X <- jt + AC
        jq1 <- sr
        jt, X <- jt + AC
        jq2 <- sr
        jt, X <- jt + AC
        jq3 <- sr
        jt, X <- jt + AC
        jq4 <- sr
        jt, X <- jt + AC
        jq5 <- sr
        jt, X <- jt + AC
        jq6 <- sr
        jt, X <- jt + AC
        jq7 <- sr
        AC <- #16               ; the tail on, published
        jrtail <- jrtail + AC
        AC <- jrmask
        jrtail <- jrtail & AC
        AC <- jidx
        F <- #I_REQTAIL + AC | X <- F
        F <- jrtail
        sr <- F
        F <- jq7
        jtag <- F
        F <- jq6
        jdone <- F
        jstat <- #ST_OK
        AC <- #OP_SERVER
        F <- jq0 - AC | if carry goto jr_server
        AC <- jq0
        X <- #OPTAB + AC
        F <- [X] | goto F
        nop

jr_copy: F <- jq2
        jalo <- F
        F <- jq3
        jahi <- F
        F <- jq4
        jblo <- F
        F <- jq5
        jbhi <- F
        F <- jq6
        jleft <- F
        AC <- jq2
        AC <- jq4 | AC
        AC <- jq6 | AC
        AC <- #1 & AC
        F <- m1 + AC | if carry goto jr_align
        nop
        F <- jcl - 1 | ifnot carry goto jrc_go    ; the kernel's ring: no windows
        F <- jq2
        jt2 <- F
        F <- jq3
        jt3 <- F
        jret <- #jrc_b
        goto jwcheck
        nop
jrc_b:  F <- jq4
        jt2 <- F
        F <- jq5
        jt3 <- F
        jret <- #jrc_go
        goto jwcheck
        nop
jrc_go: goto js_copy
        jend <- #jr_done

jr_zero: jblo <- 0 | goto jr_fz
        nop
jr_fill: F <- jq4
        jblo <- F
jr_fz:  F <- jq2
        jalo <- F
        F <- jq3
        jahi <- F
        F <- jq6
        jleft <- F
        AC <- jq2
        AC <- jq6 | AC
        AC <- #1 & AC
        F <- m1 + AC | if carry goto jr_align
        nop
        F <- jcl - 1 | ifnot carry goto jrf_go
        F <- jq2
        jt2 <- F
        F <- jq3
        jt3 <- F
        jret <- #jrf_go
        goto jwcheck
        nop
jrf_go: goto js_fill
        jend <- #jr_done

jr_badop: goto jr_fail
        jstat <- #ST_BADOP
jr_align: goto jr_fail
        jstat <- #ST_ALIGN
jr_window: goto jr_fail
        jstat <- #ST_WINDOW
jr_fail: jdone <- 0

; The request is done: its completion, then the next.
jr_done: F <- jset
        t0 <- F
        F <- jtag
        t1 <- F
        F <- jstat
        t2 <- F
        F <- jdone
        t3 <- F
        t4 <- 0
        t7 <- #jr_next
        goto cpost
        nop
jr_next: jirq <- #1
jr_on:  jres <- #jring
        ifnot attn goto jring
        nop
        TICK jring 0

; The ring is empty: the client's interrupt, if it has completions it
; hasn't been told of, and out of the queue until its doorbell.
jr_empty: F <- jirq - 1 | ifnot carry goto jstop
        jres <- #jring
        jirq <- 0
        AC <- jset
        X <- #R_LEVEL + AC
        F <- [X] - 1 | ifnot carry goto jstop      ; it has no interrupt
        F <- [X]
        t2 <- F
        X <- #R_CPU16 + AC
        F <- [X]
        t1 <- F
        X <- #R_HOLD + AC
        F <- [X]
        t3 <- F
        X <- #R_CL + AC
        AC <- [X]
        AC <- #SRC_RING + AC
        t0 <- AC
        t7 <- #jstop
        goto post
        nop

; Any other op, to the Forth's server through REQQ. When that's full the
; job tries again after the native layer has run.
jr_server: X <- #REQHEAD
        AC <- [X]
        AC <- #16 + AC
        AC <- #0xF0 & AC
        jt <- AC                ; the head after this one
        X <- #REQTAIL
        AC <- [X] ^ AC
        F <- m1 + AC | ifnot carry goto jr_full
        X <- #REQHEAD
        AC <- [X]
        jt2, X <- #REQQ + AC
        F <- jcl
        [X] <- F
        jt2, X <- jt2 + 1
        F <- jq0
        [X] <- F
        jt2, X <- jt2 + 1
        F <- jq1
        [X] <- F
        jt2, X <- jt2 + 1
        F <- jq2
        [X] <- F
        jt2, X <- jt2 + 1
        F <- jq3
        [X] <- F
        jt2, X <- jt2 + 1
        F <- jq4
        [X] <- F
        jt2, X <- jt2 + 1
        F <- jq5
        [X] <- F
        jt2, X <- jt2 + 1
        F <- jq6
        [X] <- F
        jt2, X <- jt2 + 1
        F <- jq7
        [X] <- F
        X <- #REQHEAD
        AC <- jt
        [X] <- AC
        X <- #SERVER
        F <- [X] - 1 | ifnot carry goto jr_on
        F <- [X] | X <- F
        [X] <- 0                ; the server can run
        X <- #WOKE
        [X] <- -1 | goto jr_on
        nop
jr_full: goto jattn
        jres <- #jr_server

; Is [jt2:jt3, + jleft) inside one of client jcl's windows? Back to jret
; if so, to jr_window if not.
jwcheck: AC <- jleft
        F <- jt2 + AC
        jelo <- F | ifnot carry goto jw_nc
        F <- jt3
        F <- jt3 + 1            ; the end's high half, carried
jw_nc:  jehi <- F
        AC <- jset
        X <- #R_NWIN + AC
        F <- [X]
        jwn <- F
        F <- #R_WIN + AC
        jwin <- F
jw_next: jwn <- jwn - 1 | ifnot carry goto jr_window    ; none left: outside them all
        X <- jwin
        AC <- [X]               ; its base, low
        F <- jt2 - AC | if carry goto jw_b0
        jwin, X <- jwin + 1
        AC <- [X]               ; high, with the borrow
        F <- jt3 - AC - 1 | ifnot carry goto jw_f1  ; the start is below it
        nop
        goto jw_lim
        nop
jw_b0:  AC <- [X]
        F <- jt3 - AC | ifnot carry goto jw_f1
        nop
jw_lim: jwin, X <- jwin + 1     ; its limit, low
        AC <- jelo
        F <- [X] - AC | if carry goto jw_l0
        jwin, X <- jwin + 1
        AC <- jehi
        F <- [X] - AC - 1 | ifnot carry goto jw_f3  ; the end is beyond it
        nop
        F <- jret | goto F
        nop
jw_l0:  AC <- jehi
        F <- [X] - AC | ifnot carry goto jw_f3
        nop
        F <- jret | goto F
        nop
jw_f1:  AC <- #3
        jwin <- jwin + AC | goto jw_next
        nop
jw_f3:  jwin <- jwin + 1 | goto jw_next
        nop
