; wordfreq: word frequencies of a text read from the console. A word is a
; (The system's copy: console input goes through lib/start.s's UART routines,
; since the UART needs to be asked first.)
; maximal run of ASCII letters, compared case-insensitively. Prints the
; number of words, the number of distinct words, and the 15 most frequent
; as "count word", by count descending, ties in alphabetical order.
;
; Each word is built in lower case straight into a string pool (a 256-byte
; table maps letters to lower case and everything else to 0), hashing as it
; goes (h = h * 31 + c). An open-addressing hash table of 256 entries
; {word, count} then either counts it, or keeps it by moving the pool's
; free pointer past it. The used entries are collected into an array of
; pointers and insertion-sorted.
;
;! input-file: ../../../v1_isa/programs/common/wordfreq.txt

        .include "lib/start.s"

SLOTS   = 256                   ; hash table entries (8 bytes each): {word, count}
TOPN    = 15

main:   SAVE r8-r14
        ; r9 = start of the current word in the pool,
        ; r10 = where its next letter goes, r11 = its hash,
        ; r12 = 31 (MULU has no immediate form), r13 = probe index,
        ; r14 = the hash table.
        MOV  r9, #pool
        MOV  r10, r9
        MOV  r12, #31
        MOV  r14, #table
.skip:  BSR  __con_getc         ; between words: -1 at the end of the input
        BMI  .eof
        MOV  r1, byte [lower + r1]
        BEQ  .skip
        MOV  r11, #0
.inword:
        ST   r1, byte [r10]+    ; append the letter
        MULU r11, r12           ; h = h * 31 + c
        ADD  r11, r1
        BSR  __con_getc
        BMI  .endword           ; the end of the input also ends a word
        MOV  r1, byte [lower + r1]
        BNE  .inword
.endword:
        ST   r0, byte [r10]     ; NUL-terminate the word in place
        MOV  r13, r11
        AND  r13, #SLOTS - 1
.probe: MOV  r1, [r14 + r13*8]  ; the entry's word, 0 = free
        BEQ  .new
        MOV  r2, r9
        BSR  strcmp
        TST  r1, r1             ; (strcmp's result doesn't come with flags)
        BEQ  .found
        ADD  r13, #1            ; linear probing
        AND  r13, #SLOTS - 1
        BRA  .probe
.found: MOV  r1, [r14 + r13*8 + 4]
        ADD  r1, #1
        ST   r1, [r14 + r13*8 + 4]
        MOV  r10, r9            ; drop the copy: the pool space is reused
        BRA  .skip
.new:   ST   r9, [r14 + r13*8]
        MOV  r1, #1
        ST   r1, [r14 + r13*8 + 4]
        LEA  r9, [r10 + 1]      ; keep the word: the pool moves past its NUL
        MOV  r10, r9
        BRA  .skip

        ; Collect the used entries into order[], adding up the counts.
.eof:   MOV  r1, r14
        LEA  r2, [r14 + 8 * SLOTS]
        MOV  r8, #order         ; r8 = order[0]
        MOV  r9, r8             ; r9 = the end of order[]
        MOV  r10, #0            ; r10 = number of words
.coll:  MOV  r3, [r1]
        BEQ  .empty
        ST   r1, [r9]+
        ADD  r10, [r1 + 4]
.empty: ADD  r1, #8
        CMP  r1, r2
        BNE  .coll
        MOV  r1, #s_words
        BSR  puts
        MOV  r1, r10
        BSR  print_u32
        BSR  newline
        MOV  r1, #s_distinct
        BSR  puts
        MOV  r1, r9
        SUB  r1, r8
        LSR  r1, #2
        BSR  print_u32
        BSR  newline

        ; Insertion sort of order[]: more frequent first, then alphabetical.
        ; r10 = &order[i], r11 = x = order[i], r13 = x's count,
        ; r14 = x's word, r12 = the hole x moves down through.
        MOV  r10, r8
        BRA  .next
.outer: MOV  r11, [r10]
        MOV  r13, [r11 + 4]
        MOV  r14, [r11]
        MOV  r12, r10
.inner: CMP  r12, r8
        BEQ  .place
        MOV  r2, -[r12]         ; y = the entry in front of the hole
        CMP  r13, [r2 + 4]
        BLO  .back              ; x is less frequent: it stays behind y
        BNE  .shift             ; more frequent: it goes in front
        MOV  r1, r14            ; same count: alphabetical order decides
        MOV  r2, [r2]
        BSR  strcmp
        TST  r1, r1
        BPL  .back              ; (distinct words are never equal)
        MOV  r2, [r12]
.shift: ST   r2, [r12 + 4]      ; y moves up into the hole
        BRA  .inner
.back:  ADD  r12, #4
.place: ST   r11, [r12]
.next:  ADD  r10, #4
        CMP  r10, r9
        BLO  .outer

        ; Print the first TOPN (or all, if there are fewer).
        LEA  r11, [r8 + 4 * TOPN]
        CMP  r11, r9
        BLS  .top
        MOV  r11, r9
.top:   MOV  r10, r8
.print: MOV  r12, [r10]+
        MOV  r1, [r12 + 4]
        BSR  print_u32
        BSR  space
        MOV  r1, [r12]
        BSR  puts
        BSR  newline
        CMP  r10, r11
        BNE  .print
        RESTORE r8-r14
        RET

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/string.s"

; ---- data ----

s_words:    .asciz "words: "
s_distinct: .asciz "distinct: "

; lower[c]: the lower-case letter for an ASCII letter, 0 for anything else.
lower:  .space 'A'
        .ascii "abcdefghijklmnopqrstuvwxyz"
        .space 'a' - 'Z' - 1
        .ascii "abcdefghijklmnopqrstuvwxyz"
        .space 255 - 'z'

        .align 4
table:  .space 8 * SLOTS        ; {word, count}; word = 0: free
order:  .space 4 * SLOTS        ; pointers to the used entries
pool:   .space 2048             ; the words, NUL-terminated (the input is
                                ; 1578 bytes, and a word plus its NUL never
                                ; takes more room than it did in the input)
