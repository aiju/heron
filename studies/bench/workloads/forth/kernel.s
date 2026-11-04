; A Forth for draft 2: the inner interpreter and the primitives. The outer
; interpreter, the dictionary's search and the compiling words are
; compiler.s; the registers, the user area and the header layout are
; forth.inc.
;
; The threading is direct: a thread is a list of cells, each the address
; of machine code, and NEXT is
;
;       JMP  [r8]+              ; PC <- the cell at ip, ip <- ip + 4
;
; one instruction, which every primitive ends with. A colon definition's
; code field is the one-parcel CALL r12: the call leaves the address after
; it, the definition's body, in r7, and docol (r12) pushes ip and starts
; the body. Words made by CREATE, CONSTANT and DOES> have a code field
; CALL [r14 + n] instead, through the user area's pointer to their
; runtime. A word's code field sits at an address that is 2 more than a
; multiple of 4, so that its body is a cell boundary.
;
; Every built-in word has a header right in front of its code, on a cell
; boundary:
;
;               .align 4
;       h_dup:  .word h_execute, dup    ; the link, the xt
;       .n:     .byte 3, "dup"          ; the name ...
;       .e:     .space (.n - .e) & 3    ; ... and zeros to a cell boundary
;       dup:    ...                     ; the code
;
; The links chain the built-ins in the order they're written, kernel.s's
; and then compiler.s's; at start-up, cold relinks each into its thread
; of the dictionary's hash table (compiler.s).
;
; Stack comments are Forth's: ( before -- after ), the top on the right.
; Flags are -1 for true and 0 for false. Division is symmetric (DIVS
; rounds toward zero).

        .include "forth.inc"

        .global docol, dovar, docon, dodoes, xexit, lit, branch, zbranch
        .global xdo, xqdo, xloop, xploop, xsquote, xdoes, h_report
        .global cf_docol, cf_dovar, cf_docon, cf_dodoes
        .far corpus

; ---- the code fields --------------------------------------------------------
; The code fields defining words lay down, each one parcel; compiler.s
; copies them from here. (Never run in place.)

cf_docol:  CALL r12
cf_dovar:  CALL [r14 + U_DOVAR]
cf_docon:  CALL [r14 + U_DOCON]
cf_dodoes: CALL [r14 + U_DODOES]

; ---- the runtimes: what code fields call ------------------------------------
; r7 holds the body address the call left.

; docol: a colon definition's body, run as a thread, after which EXIT
; returns to the caller's thread.
docol:  PUSH r8
        MOV  r8, r7
        JMP  [r8]+

; dovar: CREATE's words and variables push their body's address. The cell
; after the code field is the DOES> cell, unused until DOES> makes the
; word dodoes's, so the body proper starts after it.
dovar:  MOV  -[r9], r11
        LEA  r11, [r7 + 4]
        JMP  [r8]+

; docon: a constant pushes its body's one cell.
docon:  MOV  -[r9], r11
        MOV  r11, [r7]
        JMP  [r8]+

; dodoes: the child of a defining word with DOES>: its body address, past
; the DOES> cell, on the data stack, and the thread the DOES> cell points
; to (the defining word's code after DOES>) run as a colon definition.
dodoes: MOV  -[r9], r11
        LEA  r11, [r7 + 4]
        PUSH r8
        MOV  r8, [r7]
        JMP  [r8]+

; ---- what the compiler compiles: no headers ---------------------------------

; lit ( -- x ): the cell after it in the thread.
lit:    MOV  -[r9], r11
        MOV  r11, [r8]+
        JMP  [r8]+

; branch: to the address in the cell after it.
branch: MOV  r8, [r8]
        JMP  [r8]+

; zbranch ( x -- ): branch if x is 0, else skip the address.
zbranch:
        TST  r11, r11
        MOV  r11, [r9]+         ; MOV leaves the flags
        BEQ  branch
        ADD  r8, #4
        JMP  [r8]+

; A loop's frame on the return stack, from DO to LOOP:
;   [sp]      the index
;   [sp + 4]  the limit
;   [sp + 8]  the address after the loop, for LEAVE
; xdo ( limit index -- ), with the address after the loop in the next cell.
xdo:    MOV  r3, [r8]+
        MOV  r2, [r9]+
        MOV  r1, r11
        MOV  r11, [r9]+
        SAVE r1-r3
        JMP  [r8]+

; xqdo ( limit index -- ): ?DO, which skips the loop if they're equal.
xqdo:   MOV  r2, [r9]+
        MOV  r1, r11
        MOV  r11, [r9]+
        CMP  r1, r2
        BEQ  branch
        MOV  r3, [r8]+
        SAVE r1-r3
        JMP  [r8]+

; xloop: the index + 1; back to the address in the next cell until it
; reaches the limit.
xloop:  MOV  r1, [sp]
        INC  r1
        CMP  r1, [sp + 4]
        BEQ  .done
        MOV  [sp], r1
        MOV  r8, [r8]
        JMP  [r8]+
.done:  ADD  sp, #12
        ADD  r8, #4
        JMP  [r8]+

; xploop ( n -- ): the index + n; back until the index crosses the
; boundary between limit - 1 and limit, either way. Biased by 2^31, the
; index - limit crosses it where a signed addition overflows.
xploop: MOV  r1, [sp]
        MOV  r2, r1
        SUB  r2, [sp + 4]
        XOR  r2, #0x80000000
        ADD  r2, r11
        BVS  .done
        ADD  r1, r11
        MOV  [sp], r1
        MOV  r11, [r9]+
        MOV  r8, [r8]
        JMP  [r8]+
.done:  ADD  sp, #12
        MOV  r11, [r9]+
        ADD  r8, #4
        JMP  [r8]+

; xsquote ( -- c-addr u ): S"'s string, inline: a count cell, then the
; characters, padded to a cell.
xsquote:
        MOV  -[r9], r11
        MOV  r11, [r8]+
        MOV  -[r9], r8
        LEA  r8, [r8 + r11*1 + 3]
        AND  r8, #-4
        JMP  [r8]+

; xdoes: DOES> at run time, in the defining word: the newest word (the one
; CREATE just made) becomes dodoes's, running the rest of this thread, and
; the defining word returns.
xdoes:  MOV  r1, [r14 + U_LATEST]
        MOV  r1, [r1 + H_XT]
        MOV  r2, half [cf_dodoes]
        MOV  half [r1], r2
        MOV  [r1 + 2], r8
        POP  r8
        JMP  [r8]+

; ---- control ----------------------------------------------------------------

        .align 4
h_exit: .word 0, xexit
.n:     .byte 4, "exit"
.e:     .space (.n - .e) & 3
; exit: back to the thread that called this one.
xexit:  POP  r8
        JMP  [r8]+

        .align 4
h_execute:
        .word h_exit, execute
.n:     .byte 7, "execute"
.e:     .space (.n - .e) & 3
; execute ( xt -- )
execute:
        MOV  r1, r11
        MOV  r11, [r9]+
        JMP  r1

; ---- the data stack ---------------------------------------------------------

        .align 4
h_dup:  .word h_execute, dup
.n:     .byte 3, "dup"
.e:     .space (.n - .e) & 3
; dup ( x -- x x )
dup:    MOV  -[r9], r11
        JMP  [r8]+

        .align 4
h_drop: .word h_dup, drop
.n:     .byte 4, "drop"
.e:     .space (.n - .e) & 3
; drop ( x -- )
drop:   MOV  r11, [r9]+
        JMP  [r8]+

        .align 4
h_swap: .word h_drop, swap
.n:     .byte 4, "swap"
.e:     .space (.n - .e) & 3
; swap ( a b -- b a )
swap:   MOV  r1, [r9]
        MOV  [r9], r11
        MOV  r11, r1
        JMP  [r8]+

        .align 4
h_over: .word h_swap, over
.n:     .byte 4, "over"
.e:     .space (.n - .e) & 3
; over ( a b -- a b a )
over:   MOV  r1, [r9]
        MOV  -[r9], r11
        MOV  r11, r1
        JMP  [r8]+

        .align 4
h_rot:  .word h_over, rot
.n:     .byte 3, "rot"
.e:     .space (.n - .e) & 3
; rot ( a b c -- b c a )
rot:    MOV  r1, [r9 + 4]
        MOV  r2, [r9]
        MOV  [r9 + 4], r2
        MOV  [r9], r11
        MOV  r11, r1
        JMP  [r8]+

        .align 4
h_mrot: .word h_rot, mrot
.n:     .byte 4, "-rot"
.e:     .space (.n - .e) & 3
; -rot ( a b c -- c a b )
mrot:   MOV  r1, [r9 + 4]
        MOV  r2, [r9]
        MOV  [r9 + 4], r11
        MOV  [r9], r1
        MOV  r11, r2
        JMP  [r8]+

        .align 4
h_nip:  .word h_mrot, nip
.n:     .byte 3, "nip"
.e:     .space (.n - .e) & 3
; nip ( a b -- b )
nip:    ADD  r9, #4
        JMP  [r8]+

        .align 4
h_tuck: .word h_nip, tuck
.n:     .byte 4, "tuck"
.e:     .space (.n - .e) & 3
; tuck ( a b -- b a b )
tuck:   MOV  r1, [r9]
        MOV  [r9], r11
        MOV  -[r9], r1
        JMP  [r8]+

        .align 4
h_qdup: .word h_tuck, qdup
.n:     .byte 4, "?dup"
.e:     .space (.n - .e) & 3
; ?dup ( x -- 0 | x x )
qdup:   TST  r11, r11
        BEQ  .done
        MOV  -[r9], r11
.done:  JMP  [r8]+

        .align 4
h_2dup: .word h_qdup, twodup
.n:     .byte 4, "2dup"
.e:     .space (.n - .e) & 3
; 2dup ( a b -- a b a b )
twodup: MOV  r1, [r9]
        MOV  -[r9], r11
        MOV  -[r9], r1
        JMP  [r8]+

        .align 4
h_2drop:
        .word h_2dup, twodrop
.n:     .byte 5, "2drop"
.e:     .space (.n - .e) & 3
; 2drop ( a b -- )
twodrop:
        MOV  r11, [r9 + 4]
        ADD  r9, #8
        JMP  [r8]+

        .align 4
h_pick: .word h_2drop, pick
.n:     .byte 4, "pick"
.e:     .space (.n - .e) & 3
; pick ( xu ... x0 u -- xu ... x0 xu )
pick:   MOV  r11, [r9 + r11*4]
        JMP  [r8]+

        .align 4
h_depth:
        .word h_pick, depth
.n:     .byte 5, "depth"
.e:     .space (.n - .e) & 3
; depth ( -- n ): the items on the stack before it
depth:  MOV  r1, [r14 + U_SP0]
        SUB  r1, r9
        LSR  r1, #2
        MOV  -[r9], r11
        MOV  r11, r1
        JMP  [r8]+

; ---- the return stack and loops ---------------------------------------------

        .align 4
h_tor:  .word h_depth, tor
.n:     .byte 2, ">r"
.e:     .space (.n - .e) & 3
; >r ( x -- ) ( R: -- x )
tor:    PUSH r11
        MOV  r11, [r9]+
        JMP  [r8]+

        .align 4
h_rfrom:
        .word h_tor, rfrom
.n:     .byte 2, "r>"
.e:     .space (.n - .e) & 3
; r> ( -- x ) ( R: x -- )
rfrom:  MOV  -[r9], r11
        POP  r11
        JMP  [r8]+

        .align 4
h_rfetch:
        .word h_rfrom, rfetch
.n:     .byte 2, "r@"
.e:     .space (.n - .e) & 3
; r@ ( -- x ) ( R: x -- x )
rfetch: MOV  -[r9], r11
        MOV  r11, [sp]
        JMP  [r8]+

        .align 4
h_i:    .word h_rfetch, i_
.n:     .byte 1, "i"
.e:     .space (.n - .e) & 3
; i ( -- n ): the innermost loop's index
i_:     MOV  -[r9], r11
        MOV  r11, [sp]
        JMP  [r8]+

        .align 4
h_j:    .word h_i, j_
.n:     .byte 1, "j"
.e:     .space (.n - .e) & 3
; j ( -- n ): the next loop out's index
j_:     MOV  -[r9], r11
        MOV  r11, [sp + 12]
        JMP  [r8]+

        .align 4
h_leave:
        .word h_j, leave
.n:     .byte 5, "leave"
.e:     .space (.n - .e) & 3
; leave: out of the innermost loop, to the address its frame holds
leave:  MOV  r8, [sp + 8]
        ADD  sp, #12
        JMP  [r8]+

        .align 4
h_unloop:
        .word h_leave, unloop
.n:     .byte 6, "unloop"
.e:     .space (.n - .e) & 3
; unloop: drop the innermost loop's frame, before an EXIT from inside it
unloop: ADD  sp, #12
        JMP  [r8]+

; ---- arithmetic -------------------------------------------------------------

        .align 4
h_plus: .word h_unloop, plus
.n:     .byte 1, "+"
.e:     .space (.n - .e) & 3
; + ( a b -- a+b )
plus:   ADD  r11, [r9]+
        JMP  [r8]+

        .align 4
h_minus:
        .word h_plus, minus
.n:     .byte 1, "-"
.e:     .space (.n - .e) & 3
; - ( a b -- a-b )
minus:  MOV  r1, [r9]+
        SUB  r1, r11
        MOV  r11, r1
        JMP  [r8]+

        .align 4
h_star: .word h_minus, star
.n:     .byte 1, "*"
.e:     .space (.n - .e) & 3
; * ( a b -- a*b ): the low 32 bits, the same signed or not
star:   MOV  r1, [r9]+
        MULU r0:r11, r1
        JMP  [r8]+

        .align 4
h_slash:
        .word h_star, slash
.n:     .byte 1, "/"
.e:     .space (.n - .e) & 3
; / ( n d -- quot )
slash:  MOV  r1, [r9]+
        DIVS r0:r1, r11
        MOV  r11, r1
        JMP  [r8]+

        .align 4
h_mod:  .word h_slash, mod
.n:     .byte 3, "mod"
.e:     .space (.n - .e) & 3
; mod ( n d -- rem )
mod:    MOV  r1, [r9]+
        DIVS r0:r1, r11
        MOV  r11, r0
        JMP  [r8]+

        .align 4
h_slmod:
        .word h_mod, slmod
.n:     .byte 4, "/mod"
.e:     .space (.n - .e) & 3
; /mod ( n d -- rem quot )
slmod:  MOV  r1, [r9]
        DIVS r0:r1, r11
        MOV  [r9], r0
        MOV  r11, r1
        JMP  [r8]+

        .align 4
h_negate:
        .word h_slmod, negate
.n:     .byte 6, "negate"
.e:     .space (.n - .e) & 3
; negate ( n -- -n )
negate: NEG  r11
        JMP  [r8]+

        .align 4
h_abs:  .word h_negate, abs_
.n:     .byte 3, "abs"
.e:     .space (.n - .e) & 3
; abs ( n -- |n| )
abs_:   TST  r11, r11
        BPL  .done
        NEG  r11
.done:  JMP  [r8]+

        .align 4
h_min:  .word h_abs, min
.n:     .byte 3, "min"
.e:     .space (.n - .e) & 3
; min ( a b -- n )
min:    MOV  r1, [r9]+
        CMP  r1, r11
        BGE  .done
        MOV  r11, r1
.done:  JMP  [r8]+

        .align 4
h_max:  .word h_min, max
.n:     .byte 3, "max"
.e:     .space (.n - .e) & 3
; max ( a b -- n )
max:    MOV  r1, [r9]+
        CMP  r1, r11
        BLE  .done
        MOV  r11, r1
.done:  JMP  [r8]+

        .align 4
h_oneplus:
        .word h_max, oneplus
.n:     .byte 2, "1+"
.e:     .space (.n - .e) & 3
; 1+ ( n -- n+1 )
oneplus:
        INC  r11
        JMP  [r8]+

        .align 4
h_oneminus:
        .word h_oneplus, oneminus
.n:     .byte 2, "1-"
.e:     .space (.n - .e) & 3
; 1- ( n -- n-1 )
oneminus:
        DEC  r11
        JMP  [r8]+

        .align 4
h_twostar:
        .word h_oneminus, twostar
.n:     .byte 2, "2*"
.e:     .space (.n - .e) & 3
; 2* ( n -- 2n )
twostar:
        ADD  r11, r11
        JMP  [r8]+

        .align 4
h_twoslash:
        .word h_twostar, twoslash
.n:     .byte 2, "2/"
.e:     .space (.n - .e) & 3
; 2/ ( n -- n/2 ), rounding down
twoslash:
        ASR  r11, #1
        JMP  [r8]+

        .align 4
h_cells:
        .word h_twoslash, cells
.n:     .byte 5, "cells"
.e:     .space (.n - .e) & 3
; cells ( n -- 4n )
cells:  LSL  r11, #2
        JMP  [r8]+

        .align 4
h_cellplus:
        .word h_cells, cellplus
.n:     .byte 5, "cell+"
.e:     .space (.n - .e) & 3
; cell+ ( a -- a+4 )
cellplus:
        ADD  r11, #4
        JMP  [r8]+

        .align 4
h_and:  .word h_cellplus, and_
.n:     .byte 3, "and"
.e:     .space (.n - .e) & 3
; and ( a b -- a&b )
and_:   AND  r11, [r9]+
        JMP  [r8]+

        .align 4
h_or:   .word h_and, or_
.n:     .byte 2, "or"
.e:     .space (.n - .e) & 3
; or ( a b -- a|b )
or_:    OR   r11, [r9]+
        JMP  [r8]+

        .align 4
h_xor:  .word h_or, xor_
.n:     .byte 3, "xor"
.e:     .space (.n - .e) & 3
; xor ( a b -- a^b )
xor_:   XOR  r11, [r9]+
        JMP  [r8]+

        .align 4
h_invert:
        .word h_xor, invert
.n:     .byte 6, "invert"
.e:     .space (.n - .e) & 3
; invert ( x -- ~x )
invert: NOT  r11
        JMP  [r8]+

        .align 4
h_lshift:
        .word h_invert, lshift
.n:     .byte 6, "lshift"
.e:     .space (.n - .e) & 3
; lshift ( x u -- x<<u )
lshift: MOV  r1, [r9]+
        LSL  r1, r11
        MOV  r11, r1
        JMP  [r8]+

        .align 4
h_rshift:
        .word h_lshift, rshift
.n:     .byte 6, "rshift"
.e:     .space (.n - .e) & 3
; rshift ( x u -- x>>u ), logical
rshift: MOV  r1, [r9]+
        LSR  r1, r11
        MOV  r11, r1
        JMP  [r8]+

; ---- comparisons ------------------------------------------------------------

        .align 4
h_equal:
        .word h_rshift, equal
.n:     .byte 1, "="
.e:     .space (.n - .e) & 3
; = ( a b -- flag )
equal:  CMP  r11, [r9]+
        SETEQ r11
        NEG  r11
        JMP  [r8]+

        .align 4
h_notequal:
        .word h_equal, notequal
.n:     .byte 2, "<>"
.e:     .space (.n - .e) & 3
; <> ( a b -- flag )
notequal:
        CMP  r11, [r9]+
        SETNE r11
        NEG  r11
        JMP  [r8]+

        .align 4
h_less: .word h_notequal, less
.n:     .byte 1, "<"
.e:     .space (.n - .e) & 3
; < ( a b -- flag ), signed
less:   MOV  r1, [r9]+
        CMP  r1, r11
        SETLT r11
        NEG  r11
        JMP  [r8]+

        .align 4
h_greater:
        .word h_less, greater
.n:     .byte 1, ">"
.e:     .space (.n - .e) & 3
; > ( a b -- flag ), signed
greater:
        MOV  r1, [r9]+
        CMP  r1, r11
        SETGT r11
        NEG  r11
        JMP  [r8]+

        .align 4
h_uless:
        .word h_greater, uless
.n:     .byte 2, "u<"
.e:     .space (.n - .e) & 3
; u< ( a b -- flag ), unsigned
uless:  MOV  r1, [r9]+
        CMP  r1, r11
        SETLO r11
        NEG  r11
        JMP  [r8]+

        .align 4
h_zeq:  .word h_uless, zeq
.n:     .byte 2, "0="
.e:     .space (.n - .e) & 3
; 0= ( x -- flag )
zeq:    TST  r11, r11
        SETEQ r11
        NEG  r11
        JMP  [r8]+

        .align 4
h_zne:  .word h_zeq, zne
.n:     .byte 3, "0<>"
.e:     .space (.n - .e) & 3
; 0<> ( x -- flag )
zne:    TST  r11, r11
        SETNE r11
        NEG  r11
        JMP  [r8]+

        .align 4
h_zless:
        .word h_zne, zless
.n:     .byte 2, "0<"
.e:     .space (.n - .e) & 3
; 0< ( n -- flag ): the sign bit, everywhere
zless:  ASR  r11, #31
        JMP  [r8]+

        .align 4
h_zgreater:
        .word h_zless, zgreater
.n:     .byte 2, "0>"
.e:     .space (.n - .e) & 3
; 0> ( n -- flag )
zgreater:
        TST  r11, r11
        SETGT r11
        NEG  r11
        JMP  [r8]+

; ---- memory -----------------------------------------------------------------

        .align 4
h_fetch:
        .word h_zgreater, fetch
.n:     .byte 1, "@"
.e:     .space (.n - .e) & 3
; @ ( a -- x )
fetch:  MOV  r11, [r11]
        JMP  [r8]+

        .align 4
h_store:
        .word h_fetch, store
.n:     .byte 1, "!"
.e:     .space (.n - .e) & 3
; ! ( x a -- )
store:  MOV  r1, [r9]+
        MOV  [r11], r1
        MOV  r11, [r9]+
        JMP  [r8]+

        .align 4
h_cfetch:
        .word h_store, cfetch
.n:     .byte 2, "c@"
.e:     .space (.n - .e) & 3
; c@ ( a -- c )
cfetch: MOV  r11, byte [r11]
        JMP  [r8]+

        .align 4
h_cstore:
        .word h_cfetch, cstore
.n:     .byte 2, "c!"
.e:     .space (.n - .e) & 3
; c! ( c a -- )
cstore: MOV  r1, [r9]+
        MOV  byte [r11], r1
        MOV  r11, [r9]+
        JMP  [r8]+

        .align 4
h_plusstore:
        .word h_cstore, plusstore
.n:     .byte 2, "+!"
.e:     .space (.n - .e) & 3
; +! ( n a -- ): add n to the cell at a
plusstore:
        MOV  r1, [r9]+
        ADD  r1, [r11]
        MOV  [r11], r1
        MOV  r11, [r9]+
        JMP  [r8]+

        .align 4
h_count:
        .word h_plusstore, count
.n:     .byte 5, "count"
.e:     .space (.n - .e) & 3
; count ( c-addr -- c-addr+1 u ): a counted string's characters
count:  MOV  r1, byte [r11]+
        MOV  -[r9], r11
        MOV  r11, r1
        JMP  [r8]+

        .align 4
h_move: .word h_count, move
.n:     .byte 4, "move"
.e:     .space (.n - .e) & 3
; move ( src dst u -- ): copy u bytes, right however they overlap: up
; from the start unless dst is above src, by cells when all three are
; multiples of 4.
move:   MOV  r3, r11
        MOV  r2, [r9]+
        MOV  r1, [r9]+
        MOV  r11, [r9]+
        TST  r3, r3
        BEQ  .done
        MOV  r4, r1
        OR   r4, r2
        OR   r4, r3
        AND  r4, #3
        BNE  .bytes
        LSR  r3, #2
        CMP  r2, r1
        BHI  .wdown
.wup:   MOV  r4, [r1]+
        MOV  [r2]+, r4
        DBNZ r3, .wup
        JMP  [r8]+
.wdown: MOV  r4, [r1 + r3*4 - 4]
        MOV  [r2 + r3*4 - 4], r4
        DBNZ r3, .wdown
        JMP  [r8]+
.bytes: CMP  r2, r1
        BHI  .bdown
.bup:   MOV  r4, byte [r1]+
        MOV  byte [r2]+, r4
        DBNZ r3, .bup
        JMP  [r8]+
.bdown: MOV  r4, byte [r1 + r3*1 - 1]
        MOV  byte [r2 + r3*1 - 1], r4
        DBNZ r3, .bdown
.done:  JMP  [r8]+

        .align 4
h_fill: .word h_move, fill
.n:     .byte 4, "fill"
.e:     .space (.n - .e) & 3
; fill ( a u c -- ): u bytes of c from a, by cells when a and u are
; multiples of 4
fill:   MOV  r3, [r9]+
        MOV  r1, [r9]+
        TST  r3, r3
        BEQ  .done
        MOV  r2, r1
        OR   r2, r3
        AND  r2, #3
        BNE  .bytes
        LSR  r3, #2
        AND  r11, #0xFF         ; c in every byte of a cell
        MOV  r2, r11
        LSL  r2, #8
        OR   r11, r2
        MOV  r2, r11
        SWAP r2
        OR   r11, r2
.cells: MOV  [r1]+, r11
        DBNZ r3, .cells
        BRA  .done
.bytes: MOV  byte [r1]+, r11
        DBNZ r3, .bytes
.done:  MOV  r11, [r9]+
        JMP  [r8]+

        .align 4
h_compare:
        .word h_fill, compare
.n:     .byte 7, "compare"
.e:     .space (.n - .e) & 3
; compare ( a1 u1 a2 u2 -- n ): two strings in the order of their
; characters, unsigned: -1 if the first comes first, 0 if they're the same,
; 1 if it comes after; a prefix comes first.
compare:
        MOV  r4, r11
        MOV  r3, [r9]+
        MOV  r2, [r9]+
        MOV  r1, [r9]+
        MOV  r5, r2             ; the shorter length
        CMP  r5, r4
        BLS  .min
        MOV  r5, r4
.min:   TST  r5, r5
        BEQ  .lens
.loop:  MOV  r6, byte [r1]+
        CMP  r6, byte [r3]+
        BNE  .order
        DBNZ r5, .loop
.lens:  CMP  r2, r4             ; the same as far as the shorter goes
.order: MOV  r11, #0
        BEQ  .done
        MOV  r11, #1
        BHI  .done
        MOV  r11, #-1
.done:  JMP  [r8]+

; ---- the dictionary's space -------------------------------------------------

        .align 4
h_here: .word h_compare, here
.n:     .byte 4, "here"
.e:     .space (.n - .e) & 3
; here ( -- a ): the next free byte of the dictionary
here:   MOV  -[r9], r11
        MOV  r11, [r14 + U_HERE]
        JMP  [r8]+

        .align 4
h_allot:
        .word h_here, allot
.n:     .byte 5, "allot"
.e:     .space (.n - .e) & 3
; allot ( n -- ): take n bytes of the dictionary
allot:  MOV  r1, [r14 + U_HERE]
        ADD  r1, r11
        MOV  [r14 + U_HERE], r1
        MOV  r11, [r9]+
        JMP  [r8]+

        .align 4
h_comma:
        .word h_allot, comma
.n:     .byte 1, ","
.e:     .space (.n - .e) & 3
; , ( x -- ): x into the next cell of the dictionary
comma:  MOV  r1, [r14 + U_HERE]
        MOV  [r1]+, r11
        MOV  [r14 + U_HERE], r1
        MOV  r11, [r9]+
        JMP  [r8]+

        .align 4
h_ccomma:
        .word h_comma, ccomma
.n:     .byte 2, "c,"
.e:     .space (.n - .e) & 3
; c, ( c -- ): c into the next byte of the dictionary
ccomma: MOV  r1, [r14 + U_HERE]
        MOV  byte [r1]+, r11
        MOV  [r14 + U_HERE], r1
        MOV  r11, [r9]+
        JMP  [r8]+

        .align 4
h_align:
        .word h_ccomma, align
.n:     .byte 5, "align"
.e:     .space (.n - .e) & 3
; align: here to a cell boundary
align:  MOV  r1, [r14 + U_HERE]
        ADD  r1, #3
        AND  r1, #-4
        MOV  [r14 + U_HERE], r1
        JMP  [r8]+

        .align 4
h_aligned:
        .word h_align, aligned
.n:     .byte 7, "aligned"
.e:     .space (.n - .e) & 3
; aligned ( a -- a' ): a up to a cell boundary
aligned:
        ADD  r11, #3
        AND  r11, #-4
        JMP  [r8]+

; ---- the benchmark's input and output ---------------------------------------

        .align 4
h_corpus:
        .word h_aligned, xcorpus
.n:     .byte 6, "corpus"
.e:     .space (.n - .e) & 3
; corpus ( -- c-addr u ): the text the workload gives the program to read
xcorpus:
        MOV  -[r9], r11
        MOV  r1, #corpus
        MOV  -[r9], r1
        MOV  r11, [corpus_len]
        JMP  [r8]+

        .align 4
h_report:                       ; the newest of kernel.s's: compiler.s's link to them
        .word h_corpus, report
.n:     .byte 6, "report"
.e:     .space (.n - .e) & 3
; report ( x c-addr u -- ): a result line on the console, "label x" with
; x in hex (bench_report): what the program found, at its end
report: MOV  r3, r11
        MOV  r2, [r9]+
        MOV  r5, [r9]+
        MOV  r11, [r9]+
        MOV  r1, #labelbuf
        CMP  r3, #LABEL_MAX
        BLS  .copy
        MOV  r3, #LABEL_MAX
.copy:  TST  r3, r3
        BEQ  .end
.loop:  MOV  r4, byte [r2]+
        MOV  byte [r1]+, r4
        DBNZ r3, .loop
.end:   CLR  byte [r1]
        MOV  r1, #labelbuf
        MOV  r2, r5
        CALL bench_report
        JMP  [r8]+

LABEL_MAX = 63

        .bss
labelbuf:
        .space LABEL_MAX + 1
