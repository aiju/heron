; strings: the string library plus in-place reverse, uppercase and a word count.

        .include "lib/start.s"

main:   PUSH r8
        PUSH r9
        PUSH r10

        ; ---- strlen ----
        LI   r8, #lentab
.len:   LD   r9, [r8]           ; string pointer, 0 ends the table
        BEQ  .lendone
        LI   r1, #s_strlen
        CALL puts
        MOV  r1, r9
        CALL putquoted
        LI   r1, #s_is
        CALL puts
        MOV  r1, r9
        CALL strlen
        CALL print_u16
        CALL newline
        ADDI r8, 2
        BRA  .len
.lendone:

        ; ---- strcpy ----
        LI   r1, #buf
        LI   r2, #s_copyme
        CALL strcpy
        MOV  r9, r1             ; strcpy returns dst
        LI   r1, #s_strcpy
        CALL puts
        MOV  r1, r9
        CALL putquoted
        CALL newline

        ; ---- strcmp ----
        LI   r8, #cmptab
.cmp:   LD   r9, [r8]
        BEQ  .cmpdone
        LD   r10, [r8 + 2]
        LI   r1, #s_strcmp
        CALL puts
        MOV  r1, r9
        CALL putquoted
        LI   r1, #s_comma
        CALL puts
        MOV  r1, r10
        CALL putquoted
        LI   r1, #s_is
        CALL puts
        MOV  r1, r9
        MOV  r2, r10
        CALL strcmp
        CALL print_s16
        CALL newline
        ADDI r8, 4
        BRA  .cmp
.cmpdone:

        ; ---- memcpy: one call for each path through it ----
        LI   r8, #cpytab
.cpy:   LD   r3, [r8 + 4]       ; length, 0 ends the table
        BEQ  .cpydone
        LI   r1, #buf           ; buf = 32 dots
        MVI  r2, '.'
        MVI  r3, 32
        CALL memset
        STB  r0, [buf + 32]
        LD   r1, [r8]           ; dst offset into buf
        ADD  r1, #buf
        LD   r2, [r8 + 2]       ; src offset into alpha
        ADD  r2, #alpha
        LD   r3, [r8 + 4]
        CALL memcpy
        LI   r1, #s_memcpy
        CALL puts
        LI   r1, #buf
        CALL puts
        CALL newline
        ADDI r8, 6
        BRA  .cpy
.cpydone:

        ; ---- memset at odd and even addresses ----
        LI   r1, #buf
        MVI  r2, '-'
        MVI  r3, 24
        CALL memset
        STB  r0, [buf + 24]
        LI   r1, #buf + 3
        MVI  r2, '*'
        MVI  r3, 9
        CALL memset
        LI   r1, #buf + 14
        MVI  r2, '#'
        MVI  r3, 6
        CALL memset
        LI   r1, #s_memset
        CALL puts
        LI   r1, #buf
        CALL puts
        CALL newline

        ; ---- memmove, overlapping both ways ----
        LI   r1, #buf
        LI   r2, #alpha
        MVI  r3, 11
        CALL memcpy
        STB  r0, [buf + 11]
        LI   r1, #buf + 2       ; dst above src: must copy backwards
        LI   r2, #buf
        MVI  r3, 6
        CALL memmove
        LI   r1, #s_memmove
        CALL puts
        LI   r1, #buf
        CALL puts
        CALL newline
        LI   r1, #buf           ; dst below src: forwards
        LI   r2, #buf + 3
        MVI  r3, 7
        CALL memmove
        LI   r1, #s_memmove
        CALL puts
        LI   r1, #buf
        CALL puts
        CALL newline

        ; ---- reverse in place ----
        LI   r1, #buf
        LI   r2, #s_hello
        CALL strcpy
        CALL reverse
        LI   r1, #s_reverse
        CALL puts
        LI   r1, #buf
        CALL putquoted
        CALL newline

        ; ---- uppercase ----
        LI   r1, #buf
        LI   r2, #s_fox
        CALL strcpy
        CALL upcase
        LI   r1, #s_upper
        CALL puts
        LI   r1, #buf
        CALL putquoted
        CALL newline

        ; ---- word count ----
        LI   r1, #paragraph
        CALL wordcount
        MOV  r9, r1
        LI   r1, #s_words
        CALL puts
        MOV  r1, r9
        CALL print_u16
        CALL newline

        POP  r10
        POP  r9
        POP  r8
        RET

; putquoted: print the string at r1 in double quotes.
putquoted:
        PUSH r1
        MVI  r1, '"'
        CALL putc
        POP  r1
        CALL puts
        MVI  r1, '"'
        JMP  putc               ; tail call

; reverse: reverse the string at r1 in place.
reverse:
        MOV  r2, r1
.end:   LDB  r3, [r2]           ; find the NUL
        LEA  r2, [r2 + 1]
        BNE  .end
        ADDI r2, -2             ; r2 = last character, r1 = first
.loop:  CMP  r1, r2
        BHS  .done
        LDB  r3, [r1]
        LDB  r4, [r2]
        STB  r4, [r1]
        STB  r3, [r2]
        INC  r1
        DEC  r2
        BRA  .loop
.done:  RET

; upcase: convert a-z to A-Z in the string at r1, in place.
upcase:
.loop:  LDB  r2, [r1]
        BEQ  .done
        ADDI r2, -'a'           ; one unsigned compare checks both ends
        CMPI r2, 26
        BHS  .next
        ADDI r2, 'A'
        STB  r2, [r1]
.next:  INC  r1
        BRA  .loop
.done:  RET

; wordcount: r1 = text -> r1 = number of words. A word is a run of
; characters above ' '; space, tab, newline (anything <= ' ') separate them.
wordcount:
        MVI  r3, 0              ; words
        MVI  r4, 0              ; 1 inside a word
.loop:  LDB  r2, [r1]
        BEQ  .done
        INC  r1
        CMPI r2, ' '
        BLS  .blank
        TST  r4, r4
        BNE  .loop
        INC  r3                 ; first character of a word
        MVI  r4, 1
        BRA  .loop
.blank: MVI  r4, 0
        BRA  .loop
.done:  MOV  r1, r3
        RET

; ---- data ----
lentab: .word s_empty, s_x, s_hello, s_fox, 0
cmptab: .word s_abc, s_abc
        .word s_abc, s_abd
        .word s_abd, s_abc
        .word s_ab, s_abc
        .word s_abc, s_ab
        .word s_empty, s_empty
        .word s_zebra, s_apple
        .word s_hi8, s_abc      ; bytes compare unsigned: 0xE9 > 'a'
        .word 0
cpytab: .word 0, 0, 11          ; dst offset, src offset, length
        .word 3, 5, 9           ; both odd: one byte, then words
        .word 4, 1, 7           ; parities differ: bytes only
        .word 2, 2, 20          ; words: two groups of four, two more
        .word 5, 7, 1
        .word 0, 0, 0

s_strlen:   .asciz "strlen("
s_strcpy:   .asciz "strcpy -> "
s_strcmp:   .asciz "strcmp("
s_memcpy:   .asciz "memcpy  "
s_memset:   .asciz "memset  "
s_memmove:  .asciz "memmove "
s_reverse:  .asciz "reverse "
s_upper:    .asciz "upper   "
s_words:    .asciz "words in paragraph: "
s_is:       .asciz ") = "
s_comma:    .asciz ", "
s_empty:    .asciz ""
s_x:        .asciz "x"
s_hello:    .asciz "Hello, world!"
s_fox:      .asciz "The quick brown fox jumps over the lazy dog."
s_copyme:   .asciz "copy me"
s_abc:      .asciz "abc"
s_abd:      .asciz "abd"
s_ab:       .asciz "ab"
s_zebra:    .asciz "Zebra"
s_apple:    .asciz "apple"
s_hi8:      .asciz "\xE9t\xE9"
paragraph:
        .ascii "  It was the best of times, it was the worst of times,\n"
        .ascii "\tit was the age of wisdom,  it was the age of foolishness,\n"
        .ascii "it was the epoch of belief, it was the epoch of incredulity, \n"
        .asciz "it was the season of Light, it was the season of Darkness...\n\n"

        .align 2
alpha:  .ascii "0123456789abcdefghijklmnopqrstuvwxyz"
        .align 2
buf:    .space 64

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/string.s"
