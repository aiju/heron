; strings: exercises the string library (strlen, strcpy, strcmp, memcpy,
; memset, memmove), then reverses a string in place, converts one to upper
; case and counts the words in a paragraph.

        .include "lib/start.s"

main:   SAVE r7-r11

        ; ---- strlen ----
        LEA  r8, [lentab]
.len:   MOVS r9, [r8]+          ; string pointer, 0 ends the table
        BEQ  .lendone
        LEA  r1, [s_strlen]
        CALL puts
        MOV  r1, r9
        BSR  putquoted
        LEA  r1, [s_is]
        CALL puts
        MOV  r1, r9
        CALL strlen
        CALL print_u32
        CALL newline
        BRA  .len
.lendone:

        ; ---- strcpy ----
        LEA  r1, [buf]
        LEA  r2, [s_copyme]
        CALL strcpy
        MOV  r9, r1             ; strcpy returns dst
        LEA  r1, [s_strcpy]
        CALL puts
        MOV  r1, r9
        BSR  putquoted
        CALL newline

        ; ---- strcmp ----
        LEA  r8, [cmptab]
.cmp:   MOVS r9, [r8]+
        BEQ  .cmpdone
        MOV  r10, [r8]+
        LEA  r1, [s_strcmp]
        CALL puts
        MOV  r1, r9
        BSR  putquoted
        LEA  r1, [s_comma]
        CALL puts
        MOV  r1, r10
        BSR  putquoted
        LEA  r1, [s_is]
        CALL puts
        MOV  r1, r9
        MOV  r2, r10
        CALL strcmp
        CALL print_s32
        CALL newline
        BRA  .cmp
.cmpdone:

        ; ---- memcpy into a buffer of 32 dots ----
        LEA  r8, [cpytab]
.cpy:   MOV  r9, byte [r8]+     ; dst offset into buf
        MOV  r10, byte [r8]+    ; src offset into alpha
        MOVS r11, byte [r8]+    ; length, 0 ends the table
        BEQ  .cpydone
        LEA  r1, [buf]
        MOV  r2, #'.'
        MOV  r3, #32
        CALL memset
        CLR  byte [buf + 32]
        LEA  r1, [buf + r9]
        LEA  r2, [alpha + r10]
        MOV  r3, r11
        CALL memcpy
        LEA  r1, [s_memcpy]
        CALL puts
        LEA  r1, [buf]
        CALL puts
        CALL newline
        BRA  .cpy
.cpydone:

        ; ---- memset at unaligned addresses ----
        LEA  r1, [buf]
        MOV  r2, #'-'
        MOV  r3, #24
        CALL memset
        CLR  byte [buf + 24]
        LEA  r1, [buf + 3]      ; head bytes, then two words
        MOV  r2, #'*'
        MOV  r3, #9
        CALL memset
        LEA  r1, [buf + 14]     ; head bytes, one word
        MOV  r2, #'#'
        MOV  r3, #6
        CALL memset
        LEA  r1, [s_memset]
        CALL puts
        LEA  r1, [buf]
        CALL puts
        CALL newline

        ; ---- memmove, overlapping both ways ----
        LEA  r1, [buf]
        LEA  r2, [alpha]
        MOV  r3, #11
        CALL memcpy
        CLR  byte [buf + 11]
        LEA  r1, [buf + 2]      ; dst above src: must copy backwards
        LEA  r2, [buf]
        MOV  r3, #6
        CALL memmove
        LEA  r1, [s_memmove]
        CALL puts
        LEA  r1, [buf]
        CALL puts
        CALL newline
        LEA  r1, [buf]          ; dst below src: forwards
        LEA  r2, [buf + 3]
        MOV  r3, #7
        CALL memmove
        LEA  r1, [s_memmove]
        CALL puts
        LEA  r1, [buf]
        CALL puts
        CALL newline

        ; ---- reverse in place ----
        LEA  r1, [buf]
        LEA  r2, [s_hello]
        CALL strcpy
        BSR  reverse
        LEA  r1, [s_reverse]
        CALL puts
        LEA  r1, [buf]
        BSR  putquoted
        CALL newline

        ; ---- upper case ----
        LEA  r1, [buf]
        LEA  r2, [s_fox]
        CALL strcpy
        BSR  upcase
        LEA  r1, [s_upper]
        CALL puts
        LEA  r1, [buf]
        BSR  putquoted
        CALL newline

        ; ---- word count ----
        LEA  r1, [s_words]
        CALL puts
        LEA  r1, [paragraph]
        BSR  wordcount
        CALL print_u32
        CALL newline

        RESTORE r7-r11
        RET

; putquoted: print the string at r1 in double quotes.
putquoted:
        PUSH r7
        PUSH r1
        MOV  r1, #'"'
        CALL putc
        POP  r1
        CALL puts
        MOV  r1, #'"'
        POP  r7
        BRA  putc               ; tail call

; reverse: reverse the string at r1 in place.
reverse:
        MOV  r2, r1
.end:   MOVS r3, byte [r2]+     ; find the NUL
        BNE  .end
        SUB  r2, #2             ; r2 = last character, r1 = first
.loop:  CMP  r1, r2
        BHS  .done              ; the pointers met (or crossed): done
        MOV  r3, byte [r1]
        MOV  r4, byte [r2]
        MOV  byte [r1]+, r4
        MOV  byte [r2], r3
        DEC  r2                 ; (there is no byte auto-decrement)
        BRA  .loop
.done:  RET

; upcase: convert a-z to A-Z in the string at r1, in place.
upcase:
.loop:  MOVS r2, byte [r1]+
        BEQ  .done
        SUB  r2, #'a'           ; one unsigned compare checks both ends of a-z
        CMP  r2, #26
        BHS  .loop
        ADD  r2, #'A'
        MOV  byte [r1 - 1], r2  ; r1 has already moved on
        BRA  .loop
.done:  RET

; wordcount: r1 = text -> r1 = number of words. A word is a run of characters
; above ' '; space, tab, newline (anything <= ' ') separate them. Two loops,
; one for each state, so the state needs no register.
wordcount:
        MOV  r3, #0             ; words
        MOV  r4, #' '           ; in a register, the compares are one parcel
.blank: MOVS r2, byte [r1]+     ; between words
        BEQ  .done
        CMP  r2, r4
        BLS  .blank
        INC  r3                 ; the first character of a word
.word:  MOVS r2, byte [r1]+     ; inside a word
        BEQ  .done
        CMP  r2, r4
        BHI  .word
        BRA  .blank
.done:  MOV  r1, r3
        RET

; ---- data ----
        .align 4
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

; memcpy cases: dst offset, src offset, length (buf and alpha are word-aligned)
cpytab: .byte 0, 0, 11          ; both aligned: two words, three bytes
        .byte 3, 5, 9           ; alignments differ: bytes only
        .byte 4, 1, 7           ; alignments differ: bytes only
        .byte 2, 2, 20          ; equally misaligned: 2 bytes, a 16-byte block, 2 bytes
        .byte 5, 7, 1           ; a single byte
        .byte 0, 0, 0

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

        .align 4
alpha:  .ascii "0123456789abcdefghijklmnopqrstuvwxyz"
        .align 4
buf:    .space 64

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/string.s"
