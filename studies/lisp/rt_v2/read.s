; The reader: characters, tokens, lists; and the symbol table.

; getc: -> r1 = the next character, or -1 at the end of the input. The
; prelude comes first (from memory, while in_ptr is set), then the console.
; Uses r1 only.
getc:   MOV  r1, [peek_ch]
        CMP  r1, #-2
        BNE  .peeked
        MOVS r1, [in_ptr]
        BEQ  .cons
        PUSH r2
        MOV  r2, r1
        MOVS r1, byte [r2]+
        BEQ  .end
        MOV  [in_ptr], r2
        POP  r2
        RET
.end:   MOV  [in_ptr], r1       ; the end of the prelude
        POP  r2
        MOV  r1, #-1
        RET
.cons:  MOV  r1, [IO_CONS]      ; a byte, or -1
        RET
.peeked:
        PUSH r1
        MOV  r1, #-2
        MOV  [peek_ch], r1
        POP  r1
        RET

; ungetc: r1 = a character to read again. Keeps all registers.
ungetc: MOV  [peek_ch], r1
        RET

; skipws: skip white space and comments -> r1 = the next character (read).
skipws: PUSH r7
.loop:  BSR  getc
        CMP  r1, #' '
        BLS  .space             ; space, control characters, and -1 (unsigned: no)
        CMP  r1, #';'
        BNE  .ret
.cmt:   BSR  getc
        CMP  r1, #-1
        BEQ  .ret
        CMP  r1, #10
        BNE  .cmt
        BRA  .loop
.space: CMP  r1, #-1
        BNE  .loop
.ret:   JMP  [sp]+

; delim: r1 = a character -> Z set if it ends a token. Keeps all registers.
delim:  CMP  r1, #-1
        BEQ  .ret
        CMP  r1, #' '
        BLS  .yes
        CMP  r1, #'('
        BEQ  .ret
        CMP  r1, #')'
        BEQ  .ret
        CMP  r1, #'\''
        BEQ  .ret
        CMP  r1, #'`'
        BEQ  .ret
        CMP  r1, #','
        BEQ  .ret
        CMP  r1, #'"'
        BEQ  .ret
        CMP  r1, #';'
.ret:   RET
.yes:   CMP  r1, r1             ; Z
        RET

; read: -> r1 = the next datum, or the end-of-file object.
read:   PUSH r7
        CMP  sp, [stack_limit]
        BLO  err_stack
        BSR  skipws
        CMP  r1, #-1
        BEQ  .eof
        CMP  r1, #'('
        BEQ  read_list
        CMP  r1, #')'
        BEQ  .close
        CMP  r1, #'\''
        BEQ  .quote
        CMP  r1, #'`'
        BEQ  .qquote
        CMP  r1, #','
        BEQ  .unquote
        CMP  r1, #'"'
        BEQ  read_string        ; (these three return to read's caller)
        BRA  read_token
.eof:   MOV  r1, #EOFV
        JMP  [sp]+
.close: LEA  r2, [msg_close]
        BRA  error0
.quote: MOV  r1, #S_quote + 3
        BRA  .wrap
.qquote:
        MOV  r1, #S_quasiquote + 3
        BRA  .wrap
.unquote:
        BSR  getc
        CMP  r1, #'@'
        BEQ  .splice
        BSR  ungetc
        MOV  r1, #S_unquote + 3
        BRA  .wrap
.splice:
        MOV  r1, #S_unquote_splicing + 3
.wrap:  PUSH r1                 ; (sym datum)
        BSR  read_datum
        MOV  r6, r1
        MOV  r5, r13
        BSR  cons
        MOV  r5, r1
        POP  r6
        POP  r7
        BRA  cons

; read_datum: read, where the end of the input is an error.
read_datum:
        PUSH r7
        BSR  read
        CMP  r1, #EOFV
        BEQ  err_eoi
        JMP  [sp]+

; read_list: after the "(". Jumped to from read, with the return address
; on the stack.
read_list:
        PUSH r13                ; the elements so far, reversed
.loop:  BSR  skipws
        CMP  r1, #-1
        BEQ  err_eoi
        CMP  r1, #')'
        BEQ  .end
        CMP  r1, #'.'
        BEQ  .dot
.elt:   BSR  ungetc
        BSR  read_datum
.add:   MOV  r6, r1
        MOV  r5, [sp]
        BSR  cons
        MOV  [sp], r1
        BRA  .loop
.dot:   BSR  getc               ; a lone "." makes a dotted pair
        BSR  delim
        BNE  .notdot
        BSR  ungetc
        BSR  read_datum         ; the tail
        PUSH r1
        BSR  skipws
        CMP  r1, #')'
        BNE  .bad
        POP  r2
        POP  r1
        POP  r7
        BRA  nreverse
.notdot:
        BSR  ungetc
        MOV  r1, #'.'
        BSR  ungetc2
        BSR  read_datum
        BRA  .add
.end:   POP  r1
        MOV  r2, r13
        POP  r7
        BRA  nreverse
.bad:   LEA  r2, [msg_dot]
        BRA  error0

; ungetc2: push back a second character (r1), before the one in peek_ch:
; only for "." followed by a token character, which read_token takes from
; tokpre.
ungetc2:
        MOV  [tokpre], r1
        RET

; nreverse: r1 = a list, r2 = a tail -> r1 = the list reversed in place,
; ending in the tail.
nreverse:
.loop:  CMP  r1, r13
        BEQ  .done
        MOV  r6, [r1 + 3]
        MOV  [r1 + 3], r2
        MOV  r2, r1
        MOV  r1, r6
        BRA  .loop
.done:  MOV  r1, r2
        RET

; read_string: after the opening quote. Jumped to from read, with the
; return address on the stack.
read_string:
        MOV  r4, #tokbuf
.loop:  BSR  getc
        CMP  r1, #-1
        BEQ  err_eoi
        CMP  r1, #'"'
        BEQ  .end
        CMP  r1, #'\\'
        BNE  .put
        BSR  getc
        CMP  r1, #-1
        BEQ  err_eoi
        CMP  r1, #'n'
        BNE  .put
        MOV  r1, #10
.put:   CMP  r4, #tokbuf_end
        BHS  .loop              ; too long: drop the rest
        MOV  byte [r4]+, r1
        BRA  .loop
.end:   MOV  r1, r4
        SUB  r1, #tokbuf
        MOV  r2, #tokbuf
        BRA  make_string_t

; make_string: r1 = length, r2 = the bytes (not in the heap) -> r1 = a new
; string.
make_string:
        PUSH r7
make_string_t:
        PUSH r1
        PUSH r2
        MOV  r2, r1
        ADD  r2, #8 + 7
        AND  r2, #-8
        BSR  alloc
        POP  r10                ; the bytes
        POP  r2                 ; the length
        MOV  r5, r2
        LSL  r5, #8
        OR   r5, #B_STR
        MOV  [r1], r5
        LEA  r5, [not_proc]
        MOV  [r1 + 4], r5
        LEA  r9, [r1 + 8]       ; (byte pointers into the heap stay in r9-r12)
.copy:  SUB  r2, #1
        BLO  .done
        MOV  r11, byte [r10]+
        MOV  byte [r9]+, r11
        BRA  .copy
.done:  OR   r1, #3
        JMP  [sp]+

; read_token: r1 = its first character. Jumped to from read, with the
; return address on the stack.
read_token:
        MOV  r4, #tokbuf
        MOVS r2, [tokpre]       ; a "." pushed back by read_list
        BEQ  .first
        MOV  byte [r4]+, r2
        CLR  [tokpre]
.first: MOV  byte [r4]+, r1
.loop:  BSR  getc
        BSR  delim
        BEQ  .end
        CMP  r4, #tokbuf_end
        BHS  .loop
        MOV  byte [r4]+, r1
        BRA  .loop
.end:   BSR  ungetc
        MOV  r3, r4             ; the end
        ; an integer? [+-]?[0-9]+
        MOV  r4, #tokbuf
        MOV  r8, #0             ; negative?
        MOV  r1, byte [r4]
        CMP  r1, #'-'
        BEQ  .sign
        CMP  r1, #'+'
        BNE  .digits
        BRA  .sign2
.sign:  MOV  r8, #1
.sign2: ADD  r4, #1
        CMP  r4, r3
        BEQ  .symbol            ; just a sign
.digits:
        MOV  r2, #0             ; the value
        MOV  r6, r4
.dig:   MOV  r1, byte [r6]+
        SUB  r1, #'0'
        CMP  r1, #9
        BHI  .symbol
        CMP  r2, #107374182     ; would value * 10 + 9 overflow 2^30?
        BHI  .ovf
        MOV  r5, r2
        LSL  r2, #3
        ADD  r2, r5
        ADD  r2, r5
        ADD  r2, r1
        CMP  r6, r3
        BNE  .dig
        MOV  r1, #0x40000000    ; 2^30: only as -2^30
        CMP  r2, r1
        BHI  .ovf
        BLO  .ok
        CMP  r8, #0
        BEQ  .ovf
.ok:    CMP  r8, #0
        BEQ  .pos
        NEG  r2, r2
.pos:   ADD  r2, r2
        MOV  r1, r2
        JMP  [sp]+
.ovf:   BRA  err_overflow
.symbol:
        MOV  r2, r3             ; "nil" is nil
        SUB  r2, #tokbuf
        CMP  r2, #3
        BNE  .intern
        MOV  r1, byte [tokbuf]
        CMP  r1, #'n'
        BNE  .intern
        MOV  r1, byte [tokbuf + 1]
        CMP  r1, #'i'
        BNE  .intern
        MOV  r1, byte [tokbuf + 2]
        CMP  r1, #'l'
        BNE  .intern
        MOV  r1, r13
        JMP  [sp]+
.intern:
        MOV  r1, #tokbuf
        BRA  intern_t

; ---- the symbol table: 256 chains through the symbols' next fields

; hash: r1 = bytes, r2 = length -> r6 = the bucket's address. Keeps r1, r2.
hash:   PUSH r1
        PUSH r2
        MOV  r6, #0
.loop:  SUB  r2, #1
        BLO  .done
        MOV  r5, r6             ; h = h * 31 + c
        LSL  r6, #5
        SUB  r6, r5
        ADD  r6, byte [r1]+
        BRA  .loop
.done:  AND  r6, #255
        LSL  r6, #2
        ADD  r6, #symtab
        POP  r2
        POP  r1
        RET

; intern: r1 = bytes, r2 = length -> r1 = the symbol with that name.
intern: PUSH r7
intern_t:
        BSR  hash
        MOV  r9, r6             ; the bucket
        MOV  r5, [r6]           ; the chain
.next:  CMP  r5, #0
        BEQ  .new
        MOV  r4, [r5 + SYM_NAME]
        MOV  r3, [r4 - 3]
        LSR  r3, #8             ; the name's length
        CMP  r3, r2
        BNE  .skip
        LEA  r4, [r4 + STR_BYTES]
        MOV  r10, r1
.cmp:   SUB  r3, #1
        BLO  .found
        MOV  r8, byte [r4]+
        CMP  r8, byte [r10]+
        BEQ  .cmp
.skip:  MOV  r5, [r5 + SYM_NEXT]
        BRA  .next
.found: MOV  r1, r5
        JMP  [sp]+
.new:   ; the name, in constant space
        MOV  r4, [const_free]
        MOV  r3, r2
        ADD  r3, #8 + 7
        AND  r3, #-8
        ADD  r3, r4
        CMP  r3, #CONST_END
        BHI  .full
        MOV  [const_free], r3
        MOV  r3, r2
        LSL  r3, #8
        OR   r3, #B_STR
        MOV  [r4], r3
        LEA  r3, [not_proc]
        MOV  [r4 + 4], r3
        LEA  r3, [r4 + 8]
        MOV  r10, r2
.copy:  SUB  r10, #1
        BLO  .sym
        MOV  r8, byte [r1]+
        MOV  byte [r3]+, r8
        BRA  .copy
.sym:   OR   r4, #3             ; the symbol, in symbol space
        MOV  r1, [sym_free]
        LEA  r3, [r1 + 32]
        CMP  r3, #SYM_END
        BHI  .full
        MOV  [sym_free], r3
        MOV  r3, #H_SYM
        MOV  [r1], r3
        LEA  r3, [not_proc]
        MOV  [r1 + 4], r3
        MOV  r3, #UNB
        MOV  [r1 + 8], r3
        MOV  [r1 + 12], r4
        CLR  [r1 + 16]
        MOV  [r1 + 20], r13
        MOV  r3, [r9]
        MOV  [r1 + 24], r3
        MOV  [r1 + 28], r13
        OR   r1, #3
        MOV  [r9], r1
        JMP  [sp]+
.full:  LEA  r1, [msg_symfull]
        BRA  fatal

; intern_static: put the static symbols into the table.
intern_static:
        PUSH r7
        MOV  r10, #sym_static
.loop:  CMP  r10, #sym_static_end
        BHS  .done
        MOV  r4, [r10 + 12]     ; the name
        LEA  r1, [r4 + STR_BYTES]
        MOV  r2, [r4 - 3]
        LSR  r2, #8
        BSR  hash
        MOV  r5, [r6]
        MOV  [r10 + 24], r5
        LEA  r5, [r10 + 3]
        MOV  [r6], r5
        ADD  r10, #32
        BRA  .loop
.done:  JMP  [sp]+

msg_close:      .asciz "unexpected )"
msg_eoi:        .asciz "unexpected end of input"
msg_dot:        .asciz "bad syntax"
msg_symfull:    .asciz "symbol space full"
        .align 2

err_eoi:
        LEA  r1, [msg_eoi]      ; print the error, then stop: nothing more to read
        PUSH r1
        LEA  r1, [msg_error]
        BSR  puts
        POP  r1
        BSR  puts
        MOV  r1, #10
        BSR  putc
        HALT

        .align 4
tokpre: .word 0
symtab: .space 1024
tokbuf: .space 1024
tokbuf_end:
