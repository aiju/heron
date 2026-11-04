; A Forth for draft 2: the outer interpreter, the dictionary and the
; compiling words. kernel.s has the inner interpreter and the primitives,
; forth.inc the registers, the user area and the header layout.
;
; main starts the system (cold) and runs the outer interpreter over the
; program's source, forth_src (the workload's data: text whose last line
; ends in a newline, then a NUL), to its end: each blank-delimited word of
; it is looked up in the dictionary and run, or compiled into the
; definition being made, or else read as a number. Then main returns, and
; the run ends.
;
; The dictionary is a hash table of NTHREADS threads: a word's name picks
; its thread, and a thread is a linked list of headers, newest first. A
; name is compared a cell at a time: the word being looked up is copied
; into wordbuf as a counted name padded with zeros, which is how a header
; holds it, so the first cell compares the length and three characters in
; one CMP.
;
; The outer interpreter is machine code that the threads reach with NEXT:
; it runs a word by putting the word's xt in exec_thread, whose second
; cell is ran, and starting that thread, so the word's last NEXT (a
; primitive's, or EXIT's after a colon definition) comes back to it. The
; compiling words are primitives too, and immediate ones run that way in
; the middle of a definition.
;
; While compiling, the control-flow words keep their addresses on the data
; stack: IF, WHILE and DO push the address of a cell still to be filled in,
; BEGIN the address to branch back to.

        .include "forth.inc"

        .global main
        .far forth_src, dict

NTHREADS = 256                  ; the dictionary's hash table, a power of 2
NAMEMASK = ~(0xFF & ~COUNT)     ; a name's first cell without its flags
DSTACK   = 1024                 ; bytes of data stack
DICT     = 192 * 1024           ; bytes of dictionary: code and data
SBUF     = 128                  ; the longest string s" takes

        .bss
user:   .space U_SIZE           ; the user area, at r14
        .align 4
threads:
        .space NTHREADS * 4     ; each the newest header in its thread, or 0
wordbuf:
        .space 256 + 4          ; the word being looked up: count, name, zeros
sbuf:   .space SBUF             ; an interpreted s"'s string
dstack: .space DSTACK           ; the data stack, down from dstack_top
dstack_top:

        .section .farbss.forth_dict
        .align 4
dict:   .space DICT

        .data
        .align 4
exec_thread:                    ; the outer interpreter runs a word as this thread
        .word 0, ran

        .text

; ---- cold start ---------------------------------------------------------------

main:   SAVE r7-r14
        MOV  r14, #user
        MOV  [r14 + U_RP0], sp
        MOV  r1, #dict
        MOV  [r14 + U_HERE], r1
        CLR  [r14 + U_LATEST]
        CLR  [r14 + U_STATE]
        MOV  r1, #forth_src
        MOV  [r14 + U_IN], r1
        MOV  r1, #dovar
        MOV  [r14 + U_DOVAR], r1
        MOV  r1, #docon
        MOV  [r14 + U_DOCON], r1
        MOV  r1, #dodoes
        MOV  [r14 + U_DODOES], r1
        MOV  r9, #dstack_top
        MOV  [r14 + U_SP0], r9
        MOV  r12, #docol
        MOV  r1, #threads       ; an empty dictionary
        MOV  r2, #NTHREADS
.clear: CLR  [r1]+
        DBNZ r2, .clear
        MOV  r10, #h_last       ; each built-in into its thread, newest first
.hash:  MOV  r13, [r10 + H_LINK]
        MOV  r1, r10
        CALL link
        MOVS r10, r13
        BNE  .hash
        BRA  interpret

; bye: the end of the source, and so of the program.
bye:    MOVS r1, [r14 + U_STATE]
        BNE  err_unfinished
        MOV  sp, [r14 + U_RP0]
        RESTORE r7-r14
        RET

; ---- the outer interpreter ------------------------------------------------------

ran:    CMP  r9, [r14 + U_SP0]  ; back from running a word: did it take
        BHI  err_underflow      ; more than the stack had?
interpret:
        CALL parse_name
        BEQ  bye
        CALL find
        BEQ  .number
        MOV  r2, [r1 + H_XT]
        MOVS r3, byte [r1 + H_NAME]
        BMI  .run               ; IMMED, bit 7
        MOVS r3, [r14 + U_STATE]
        BEQ  .run
        MOV  r3, [r14 + U_HERE] ; compiling: the xt into the definition
        MOV  [r3]+, r2
        MOV  [r14 + U_HERE], r3
        BRA  interpret
.run:   MOV  [exec_thread], r2
        MOV  r8, #exec_thread
        JMP  [r8]+
.number:
        CALL number
        TST  r2, r2
        BEQ  err_undefined
        MOVS r3, [r14 + U_STATE]
        BNE  .literal
        MOV  -[r9], r11         ; interpreting: onto the stack
        MOV  r11, r1
        BRA  interpret
.literal:
        MOV  r3, [r14 + U_HERE] ; compiling: lit and the number
        MOV  r2, #lit
        MOV  [r3]+, r2
        MOV  [r3]+, r1
        MOV  [r14 + U_HERE], r3
        BRA  interpret

; parse_name: the next blank-delimited word of the source into wordbuf, as
; a count byte, the characters and three zeros -> r1 = its length, and Z
; set if that's 0, at the end of the source. Anything up to a space is a
; blank. The source moves on past the word and the blank after it (there
; always is one, as the source ends in a newline). Uses r2, r3.
parse_name:
        MOV  r2, [r14 + U_IN]
.skip:  MOVS r1, byte [r2]+
        BEQ  .end
        CMP  r1, #' '
        BLS  .skip
        MOV  r3, #wordbuf + 1
.copy:  MOV  byte [r3]+, r1
        MOV  r1, byte [r2]+
        CMP  r1, #' '
        BHI  .copy
        MOV  [r14 + U_IN], r2
        CLR  byte [r3]
        CLR  byte [r3 + 1]
        CLR  byte [r3 + 2]
        CMP  r3, #wordbuf + 1 + COUNT
        BHI  err_long
        MOV  r1, r3
        SUB  r1, #wordbuf + 1   ; (which clears Z)
        MOV  byte [wordbuf], r1
        RET
.end:   LEA  r2, [r2 - 1]       ; the NUL is read again next time; Z stays
        MOV  [r14 + U_IN], r2
        RET

; hash: r4 = a name's first cell w, its count and three characters,
; without flags -> r3 = the address of its thread's head: the low bits of
; w + (w >> 5) + (w >> 13). find has a copy of it inline. Uses r2.
hash:   MOV  r3, r4
        LSR  r3, #5
        ADD  r3, r4
        MOV  r2, r4
        LSR  r2, #13
        ADD  r3, r2
        AND  r3, #NTHREADS - 1
        LEA  r3, [threads + r3*4]
        RET

; find: the word in wordbuf in the dictionary -> r1 = its header, or 0
; and Z set. Uses r2-r6.
find:   MOV  r4, [wordbuf]
        MOV  r3, r4             ; hash, inline
        LSR  r3, #5
        ADD  r3, r4
        MOV  r2, r4
        LSR  r2, #13
        ADD  r3, r2
        AND  r3, #NTHREADS - 1
        MOVS r1, [threads + r3*4]
        BEQ  .done
.test:  MOV  r2, [r1 + H_NAME]
        AND  r2, #NAMEMASK
        CMP  r2, r4
        BEQ  .rest
.next:  MOVS r1, [r1 + H_LINK]
        BNE  .test
.done:  RET
.rest:  MOV  r5, byte [wordbuf] ; the first cell matches: the rest of
        CMP  r5, #4             ; the name, if it has more than 3
        BLO  .done              ; characters
        MOV  r2, [r1 + H_NAME + 4]
        CMP  r2, [wordbuf + 4]
        BNE  .next
        CMP  r5, #8             ; and more than 7: a cell at a time
        BLO  .done
        LSR  r5, #2
        DEC  r5
        LEA  r6, [r1 + H_NAME + 8]
        MOV  r3, #wordbuf + 8
.cell:  MOV  r2, [r6]+
        CMP  r2, [r3]+
        BNE  .next
        DBNZ r5, .cell
        TST  r1, r1             ; (Z clear)
        RET

; link: r1 = a header, into the head of its thread, where find finds it
; first. Uses r2-r4.
link:   PUSH r7
        MOV  r4, [r1 + H_NAME]
        AND  r4, #NAMEMASK
        CALL hash
        MOV  r2, [r3]
        MOV  [r1 + H_LINK], r2
        MOV  [r3], r1
        JMP  [sp]+

; number: the word in wordbuf as a number: decimal digits, or hex ones
; (lower case) after a $, either after a - for a negative one -> r1 = its
; value, r2 = 1; or r2 = 0 if it isn't a number. Uses r0, r3-r6.
number: MOV  r2, #wordbuf + 1
        MOV  r3, byte [wordbuf]
        MOV  r5, #0             ; negative?
        MOV  r6, #10            ; the base
        MOV  r1, byte [r2]
        CMP  r1, #'-'
        BNE  .base
        MOV  r5, #1
        INC  r2
        DEC  r3
        BEQ  .bad
.base:  MOV  r1, byte [r2]
        CMP  r1, #'$'
        BNE  .digits
        MOV  r6, #16
        INC  r2
        DEC  r3
        BEQ  .bad
.digits:
        MOV  r1, #0
.loop:  MOV  r4, byte [r2]+
        SUB  r4, #'0'
        CMP  r4, #10
        BLO  .digit
        SUB  r4, #'a' - '0' - 10
        CMP  r4, #10
        BLO  .bad
.digit: CMP  r4, r6
        BHS  .bad
        MULU r0:r1, r6
        ADD  r1, r4
        DBNZ r3, .loop
        TST  r5, r5
        BEQ  .done
        NEG  r1
.done:  MOV  r2, #1
        RET
.bad:   MOV  r2, #0
        RET

; ---- making words ---------------------------------------------------------------

; make_header: a header for the next word of the source, at here (made a
; cell boundary), and room for its code field after it, at 2 more than a
; multiple of 4 -> r1 = the header, r2 = the code field; here = the body,
; latest = the header. Not linked into the dictionary yet. Uses r3-r5.
make_header:
        PUSH r7
        CALL parse_name
        BEQ  err_noname
        MOV  r1, [r14 + U_HERE]
        ADD  r1, #3
        AND  r1, #-4
        CLR  [r1 + H_LINK]
        MOV  r5, byte [wordbuf] ; count / 4 + 1 cells of name
        LSR  r5, #2
        INC  r5
        LEA  r2, [r1 + H_NAME]
        MOV  r3, #wordbuf
.copy:  MOV  r4, [r3]+
        MOV  [r2]+, r4
        DBNZ r5, .copy
        ADD  r2, #2
        MOV  [r1 + H_XT], r2
        LEA  r3, [r2 + 2]
        MOV  [r14 + U_HERE], r3
        MOV  [r14 + U_LATEST], r1
        JMP  [sp]+

; lay: r1 into the next cell of the dictionary. Uses r2.
lay:    MOV  r2, [r14 + U_HERE]
        MOV  [r2]+, r1
        MOV  [r14 + U_HERE], r2
        RET

; make_created: CREATE's word for the next word of the source, linked:
; its code field calls dovar, then the DOES> cell. Uses r1-r5.
make_created:
        PUSH r7
        CALL make_header
        MOV  r3, half [cf_dovar]
        MOV  half [r2], r3
        MOV  r1, #0
        CALL lay
        MOV  r1, [r14 + U_LATEST]
        CALL link
        JMP  [sp]+

; ---- the defining words -----------------------------------------------------------

        .align 4
h_colon:
        .word h_report, colon   ; the last of kernel.s's built-ins
.n:     .byte 1, ":"
.e:     .space (.n - .e) & 3
; : ( "name" -- ): start a colon definition. It isn't found until ; links
; it into the dictionary, so a name it reuses means the old word in it.
colon:  CALL make_header
        MOV  r3, half [cf_docol]
        MOV  half [r2], r3
        MOV  r1, #-1
        MOV  [r14 + U_STATE], r1
        JMP  [r8]+

        .align 4
h_semi: .word h_colon, semi
.n:     .byte 1 | IMMED, 59     ; ";"
.e:     .space (.n - .e) & 3
; ; ( -- ): the end of a colon definition
semi:   MOV  r1, #xexit
        CALL lay
        MOV  r1, [r14 + U_LATEST]
        CALL link
        CLR  [r14 + U_STATE]
        JMP  [r8]+

        .align 4
h_create:
        .word h_semi, create
.n:     .byte 6, "create"
.e:     .space (.n - .e) & 3
; create ( "name" -- ): a word that pushes the address of its body, here
create: CALL make_created
        JMP  [r8]+

        .align 4
h_variable:
        .word h_create, variable
.n:     .byte 8, "variable"
.e:     .space (.n - .e) & 3
; variable ( "name" -- ): a word that pushes the address of its cell
variable:
        CALL make_created
        MOV  r1, #0
        CALL lay
        JMP  [r8]+

        .align 4
h_constant:
        .word h_variable, constant
.n:     .byte 8, "constant"
.e:     .space (.n - .e) & 3
; constant ( x "name" -- ): a word that pushes x
constant:
        CALL make_header
        MOV  r3, half [cf_docon]
        MOV  half [r2], r3
        MOV  r1, r11
        MOV  r11, [r9]+
        CALL lay
        MOV  r1, [r14 + U_LATEST]
        CALL link
        JMP  [r8]+

        .align 4
h_does: .word h_constant, does
.n:     .byte 5 | IMMED, "does>"
.e:     .space (.n - .e) & 3
; does> ( -- ): what the newest CREATE's word does, from here on in the
; definition that made it
does:   MOV  r1, #xdoes
        CALL lay
        JMP  [r8]+

        .align 4
h_immediate:
        .word h_does, immediate
.n:     .byte 9, "immediate"
.e:     .space (.n - .e) & 3
; immediate ( -- ): the newest word runs even when compiling
immediate:
        MOV  r1, [r14 + U_LATEST]
        MOV  r2, byte [r1 + H_NAME]
        OR   r2, #IMMED
        MOV  byte [r1 + H_NAME], r2
        JMP  [r8]+

; ---- compiling ------------------------------------------------------------------

        .align 4
h_lbracket:
        .word h_immediate, lbracket
.n:     .byte 1 | IMMED, "["
.e:     .space (.n - .e) & 3
; [ ( -- ): interpret, in the middle of a definition
lbracket:
        CLR  [r14 + U_STATE]
        JMP  [r8]+

        .align 4
h_rbracket:
        .word h_lbracket, rbracket
.n:     .byte 1, "]"
.e:     .space (.n - .e) & 3
; ] ( -- ): compile again
rbracket:
        MOV  r1, #-1
        MOV  [r14 + U_STATE], r1
        JMP  [r8]+

        .align 4
h_literal:
        .word h_rbracket, literal
.n:     .byte 7 | IMMED, "literal"
.e:     .space (.n - .e) & 3
; literal ( x -- ): compile x, to be pushed when the definition runs
literal:
        MOV  r1, #lit
        CALL lay
        MOV  r1, r11
        MOV  r11, [r9]+
        CALL lay
        JMP  [r8]+

        .align 4
h_tick: .word h_literal, tick
.n:     .byte 1, "'"
.e:     .space (.n - .e) & 3
; ' ( "name" -- xt )
tick:   CALL parse_xt
        MOV  -[r9], r11
        MOV  r11, r1
        JMP  [r8]+

        .align 4
h_btick:
        .word h_tick, btick
.n:     .byte 3 | IMMED, "[']"
.e:     .space (.n - .e) & 3
; ['] ( "name" -- ): compile the next word's xt, as a literal
btick:  CALL parse_xt
        PUSH r1
        MOV  r1, #lit
        CALL lay
        POP  r1
        CALL lay
        JMP  [r8]+

; parse_xt: the next word of the source, which must be defined -> r1 = its xt
parse_xt:
        PUSH r7
        CALL parse_name
        BEQ  err_noname
        CALL find
        BEQ  err_undefined
        MOV  r1, [r1 + H_XT]
        JMP  [sp]+

        .align 4
h_char: .word h_btick, char
.n:     .byte 4, "char"
.e:     .space (.n - .e) & 3
; char ( "name" -- c ): the first character of the next word
char:   CALL parse_name
        BEQ  err_noname
        MOV  -[r9], r11
        MOV  r11, byte [wordbuf + 1]
        JMP  [r8]+

        .align 4
h_bchar:
        .word h_char, bchar
.n:     .byte 6 | IMMED, "[char]"
.e:     .space (.n - .e) & 3
; [char] ( "name" -- ): compile the first character of the next word, as a
; literal
bchar:  CALL parse_name
        BEQ  err_noname
        MOV  r1, #lit
        CALL lay
        MOV  r1, byte [wordbuf + 1]
        CALL lay
        JMP  [r8]+

        .align 4
h_recurse:
        .word h_bchar, recurse
.n:     .byte 7 | IMMED, "recurse"
.e:     .space (.n - .e) & 3
; recurse ( -- ): compile a call of the definition being made
recurse:
        MOV  r1, [r14 + U_LATEST]
        MOV  r1, [r1 + H_XT]
        CALL lay
        JMP  [r8]+

        .align 4
h_squote:
        .word h_recurse, squote
.n:     .byte 2 | IMMED, 's', 34
.e:     .space (.n - .e) & 3
; s" ( "text<quote>" -- ): the text up to the next ". Compiled, it pushes
; ( c-addr u ) when the definition runs, from a copy in the definition;
; interpreted, it pushes them now, from a copy in sbuf that lasts until
; the next interpreted s".
squote: MOVS r1, [r14 + U_STATE]
        BEQ  .now
        MOV  r1, #xsquote
        CALL lay
        MOV  r3, [r14 + U_HERE] ; the count's cell, then the characters
        LEA  r4, [r3 + 4]
        CALL parse_quote
        MOV  [r3], r1
        ADD  r4, #3
        AND  r4, #-4
        MOV  [r14 + U_HERE], r4
        JMP  [r8]+
.now:   MOV  r4, #sbuf
        CALL parse_quote
        MOV  -[r9], r11
        MOV  r2, #sbuf
        MOV  -[r9], r2
        MOV  r11, r1
        JMP  [r8]+

; parse_quote: the source up to the next " copied to r4, at most SBUF
; characters -> r4 = the end of the copy, r1 = its length. Uses r2, r5,
; r6.
parse_quote:
        MOV  r2, [r14 + U_IN]
        MOV  r5, r4
        MOV  r6, #SBUF + 1
.loop:  MOVS r1, byte [r2]+
        BEQ  err_string
        CMP  r1, #34
        BEQ  .done
        MOV  byte [r4]+, r1
        DEC  r6
        BNE  .loop
        BRA  err_string
.done:  MOV  [r14 + U_IN], r2
        MOV  r1, r4
        SUB  r1, r5
        RET

        .align 4
h_paren:
        .word h_squote, paren
.n:     .byte 1 | IMMED, "("
.e:     .space (.n - .e) & 3
; ( ( "text<paren>" -- ): a comment, to the next )
paren:  MOV  r2, [r14 + U_IN]
.loop:  MOVS r1, byte [r2]+
        BEQ  .end
        CMP  r1, #')'
        BNE  .loop
        MOV  [r14 + U_IN], r2
        JMP  [r8]+
.end:   DEC  r2
        MOV  [r14 + U_IN], r2
        JMP  [r8]+

        .align 4
h_backslash:
        .word h_paren, backslash
.n:     .byte 1 | IMMED, "\\"
.e:     .space (.n - .e) & 3
; \ ( "text" -- ): a comment, to the end of the line
backslash:
        MOV  r2, [r14 + U_IN]   ; (the source's last line ends in a newline)
        MOV  r1, #10
.loop:  CMP  r1, byte [r2]+
        BNE  .loop
        MOV  [r14 + U_IN], r2
        JMP  [r8]+

; ---- control flow -------------------------------------------------------------

        .align 4
h_if:   .word h_backslash, if_
.n:     .byte 2 | IMMED, "if"
.e:     .space (.n - .e) & 3
; if ( -- orig ): a branch, if 0, to the matching ELSE or THEN
if_:    MOV  r1, #zbranch
        CALL lay
hole:   MOV  -[r9], r11         ; push here, and lay a cell to fill in later
        MOV  r11, [r14 + U_HERE]
        MOV  r1, #0
        CALL lay
        JMP  [r8]+

        .align 4
h_else: .word h_if, else_
.n:     .byte 4 | IMMED, "else"
.e:     .space (.n - .e) & 3
; else ( orig -- orig' ): a branch to THEN, and IF's branch to here
else_:  MOV  r1, #branch
        CALL lay
        MOV  r1, [r14 + U_HERE]
        MOV  r3, r11
        MOV  r11, r1
        MOV  r1, #0
        CALL lay
        MOV  r1, [r14 + U_HERE]
        MOV  [r3], r1
        JMP  [r8]+

        .align 4
h_then: .word h_else, then_
.n:     .byte 4 | IMMED, "then"
.e:     .space (.n - .e) & 3
; then ( orig -- ): IF's or ELSE's branch to here
then_:  MOV  r1, [r14 + U_HERE]
        MOV  [r11], r1
        MOV  r11, [r9]+
        JMP  [r8]+

        .align 4
h_begin:
        .word h_then, begin
.n:     .byte 5 | IMMED, "begin"
.e:     .space (.n - .e) & 3
; begin ( -- dest )
begin:  MOV  -[r9], r11
        MOV  r11, [r14 + U_HERE]
        JMP  [r8]+

        .align 4
h_until:
        .word h_begin, until
.n:     .byte 5 | IMMED, "until"
.e:     .space (.n - .e) & 3
; until ( dest -- ): back to BEGIN if 0
until:  MOV  r1, #zbranch
back:   CALL lay                ; r1, then dest
        MOV  r1, r11
        MOV  r11, [r9]+
        CALL lay
        JMP  [r8]+

        .align 4
h_again:
        .word h_until, again
.n:     .byte 5 | IMMED, "again"
.e:     .space (.n - .e) & 3
; again ( dest -- ): back to BEGIN
again:  MOV  r1, #branch
        BRA  back

        .align 4
h_while:
        .word h_again, while
.n:     .byte 5 | IMMED, "while"
.e:     .space (.n - .e) & 3
; while ( dest -- orig dest ): out to after REPEAT if 0
while:  MOV  r1, #zbranch
        CALL lay
        MOV  r1, [r14 + U_HERE]
        MOV  -[r9], r1
        MOV  r1, #0
        CALL lay
        JMP  [r8]+

        .align 4
h_repeat:
        .word h_while, repeat
.n:     .byte 6 | IMMED, "repeat"
.e:     .space (.n - .e) & 3
; repeat ( orig dest -- ): back to BEGIN, and WHILE's branch to here
repeat: MOV  r1, #branch
        CALL lay
        MOV  r1, r11
        CALL lay
        MOV  r11, [r9]+
        BRA  then_

        .align 4
h_do:   .word h_repeat, do
.n:     .byte 2 | IMMED, "do"
.e:     .space (.n - .e) & 3
; do ( -- do-sys ): start a counted loop; do-sys is the address of the
; cell that will hold the address after the loop, for LEAVE
do:     MOV  r1, #xdo
        CALL lay
        BRA  hole

        .align 4
h_qdo:  .word h_do, qdo
.n:     .byte 3 | IMMED, "?do"
.e:     .space (.n - .e) & 3
; ?do ( -- do-sys ): DO, but no times round if the index is the limit
qdo:    MOV  r1, #xqdo
        CALL lay
        BRA  hole

        .align 4
h_loop: .word h_qdo, loop
.n:     .byte 4 | IMMED, "loop"
.e:     .space (.n - .e) & 3
; loop ( do-sys -- ): the end of a DO loop, stepping by 1
loop:   MOV  r1, #xloop
endloop:
        CALL lay
        LEA  r1, [r11 + 4]      ; back to just after DO's cell
        CALL lay
        BRA  then_              ; and DO's cell is the address after

        .align 4
h_ploop:
        .word h_loop, ploop
.n:     .byte 5 | IMMED, "+loop"
.e:     .space (.n - .e) & 3
; +loop ( do-sys -- ): the end of a DO loop, stepping by the top of the stack
ploop:  MOV  r1, #xploop
        BRA  endloop

h_last = h_ploop                ; the newest built-in, where cold starts

; ---- errors: a message and the word it's about, and the machine stops ----------

err_undefined:
        LEA  r1, [.m]
        BRA  error
.m:     .asciz "undefined: "
        .align 2
err_underflow:
        LEA  r1, [.m]
        BRA  error
.m:     .asciz "stack underflow after: "
        .align 2
err_long:
        LEA  r1, [.m]
        BRA  error
.m:     .asciz "name too long: "
        .align 2
err_noname:
        LEA  r1, [.m]
        BRA  error
.m:     .asciz "the source ends without the name after: "
        .align 2
err_string:
        LEA  r1, [.m]
        BRA  error
.m:     .asciz "a string has no closing quote, after: "
        .align 2
err_unfinished:
        LEA  r1, [.m]
        BRA  error
.m:     .asciz "the source ends inside a definition, after: "
        .align 2

error:  CALL bench_puts
        MOV  r1, #wordbuf + 1
        CALL bench_puts
        MOV  r1, #10
        CALL bench_putc
        HALT
