; The printer, and reporting errors.

; putc: r1 = a byte. Keeps all registers.
putc:   MOV  byte [IO_CONS], r1
        RET

; puts: r1 = an asciz string. Uses r1, r2.
puts:   MOV  r2, r1
.loop:  MOVS r1, byte [r2]+
        BEQ  .done
        MOV  byte [IO_CONS], r1
        BRA  .loop
.done:  RET

; prin: r1 = a value; print it as write or display, by print_mode.
; Uses r1-r7 and r9. Doesn't allocate.
prin:   MOV  r2, r1
        AND  r2, #1
        BEQ  pr_int
        MOV  r2, r1
        AND  r2, #3
        CMP  r2, #1
        BEQ  pr_list
        MOV  r2, byte [r1 - 3]
        CMP  r2, #B_SYM
        BEQ  .sym
        CMP  r2, #B_STR
        BEQ  pr_str
        CMP  r2, #B_VEC
        BEQ  pr_vec
        CMP  r1, r13
        BEQ  .nil
        CMP  r1, #EOFV
        BEQ  .eof
        LEA  r1, [s_proc]
        BRA  puts
.nil:   LEA  r1, [s_nil]
        BRA  puts
.eof:   LEA  r1, [s_eof]
        BRA  puts
.sym:   MOV  r1, [r1 + SYM_NAME]
        BRA  pr_bytes

; pr_bytes: r1 = a string; its bytes as they are.
pr_bytes:
        MOV  r2, [r1 - 3]
        LSR  r2, #8
        LEA  r9, [r1 + STR_BYTES]   ; (byte pointers into the heap stay in r9-r12)
.loop:  SUB  r2, #1
        BLO  .done
        MOV  r1, byte [r9]+
        MOV  byte [IO_CONS], r1
        BRA  .loop
.done:  RET

; pr_str: a string, quoted and escaped for write.
pr_str: MOVS r5, [print_mode]
        BEQ  pr_bytes
        PUSH r7
        MOV  r2, [r1 - 3]
        LSR  r2, #8
        LEA  r9, [r1 + STR_BYTES]
        MOV  r1, #'"'
        BSR  putc
.loop:  SUB  r2, #1
        BLO  .done
        MOV  r1, byte [r9]+
        CMP  r1, #'"'
        BEQ  .esc
        CMP  r1, #'\\'
        BEQ  .esc
        CMP  r1, #10
        BNE  .put
        MOV  r1, #'\\'
        BSR  putc
        MOV  r1, #'n'
        BRA  .put
.esc:   PUSH r1
        MOV  r1, #'\\'
        BSR  putc
        POP  r1
.put:   BSR  putc
        BRA  .loop
.done:  MOV  r1, #'"'
        POP  r7
        BRA  putc

; pr_int: a fixnum, in decimal.
pr_int: PUSH r7
        ASR  r1, #1
        BPL  .pos
        PUSH r1
        MOV  r1, #'-'
        BSR  putc
        POP  r1
        NEG  r1, r1
.pos:   MOV  r6, #0
        MOV  r5, #10
.div:   DIVU r1, r5
        MFHI r2
        PUSH r2
        INC  r6
        CMP  r1, #0
        BNE  .div
.out:   POP  r1
        ADD  r1, #'0'
        BSR  putc
        DEC  r6
        BNE  .out
        JMP  [sp]+

; pr_list: a list, with a dotted tail if it has one.
pr_list:
        PUSH r7
        PUSH r1
        MOV  r1, #'('
        BSR  putc
.loop:  MOV  r1, [sp]
        MOV  r1, [r1 - 1]
        BSR  prin
        MOV  r1, [sp]
        MOV  r1, [r1 + 3]
        MOV  [sp], r1
        CMP  r1, r13
        BEQ  .close
        MOV  r2, r1
        AND  r2, #3
        CMP  r2, #1
        BNE  .dot
        MOV  r1, #' '
        BSR  putc
        BRA  .loop
.dot:   LEA  r1, [s_dot]
        BSR  puts
        MOV  r1, [sp]
        BSR  prin
.close: POP  r1
        POP  r7
        MOV  r1, #')'
        BRA  putc

; pr_vec: #(...)
pr_vec: PUSH r7
        MOV  r2, [r1 - 3]
        LSR  r2, #8
        SUB  r2, #1             ; (the call slot counts in the size)
        PUSH r2                 ; elements left
        LEA  r2, [r1 + VEC_ELTS]
        PUSH r2                 ; the next element's address (not in the heap's
                                ; way: printing never allocates)
        LEA  r1, [s_vec]
        BSR  puts
        MOVS r1, [sp + 4]
        BEQ  .close
.loop:  MOV  r2, [sp]
        MOV  r1, [r2]+
        MOV  [sp], r2
        BSR  prin
        MOV  r1, [sp + 4]
        SUB  r1, #1
        MOV  [sp + 4], r1
        BEQ  .close
        MOV  r1, #' '
        BSR  putc
        BRA  .loop
.close: ADD  sp, #8
        POP  r7
        MOV  r1, #')'
        BRA  putc

; print_value: r1 = a value, r2 = 0 for display, 1 for write.
print_value:
        MOV  [print_mode], r2
        BRA  prin

; ---- errors

; error0: r2 = the message (asciz). Print the error and abandon the form.
error0: PUSH r2
        LEA  r1, [msg_error]
        BSR  puts
        POP  r1
        BSR  puts
        BRA  err_end

; error1: r1 = the irritant, r2 = the message (asciz).
error1: PUSH r1
        PUSH r2
        LEA  r1, [msg_error]
        BSR  puts
        POP  r1
        BSR  puts
        LEA  r1, [s_colon]
        BSR  puts
        POP  r1
        MOV  r2, #1
        BSR  print_value
err_end:
        MOV  r1, #10
        BSR  putc
        BRA  abort

err_notpair:
        LEA  r2, [msg_notpair]
        BRA  error1
err_notlist:
        LEA  r2, [msg_notlist]
        BRA  error1
err_notnum:
        LEA  r2, [msg_notnum]
        BRA  error1
err_notproc:
        LEA  r2, [msg_notproc]
        BRA  error1
err_notsym:
        LEA  r2, [msg_notsym]
        BRA  error1
err_notstr:
        LEA  r2, [msg_notstr]
        BRA  error1
err_notvec:
        LEA  r2, [msg_notvec]
        BRA  error1
err_unbound:
        LEA  r2, [msg_unbound]
        BRA  error1
err_range:
        LEA  r2, [msg_range]
        BRA  error1
err_syntax:
        LEA  r2, [msg_syntax]
        BRA  error1
err_argc:
        LEA  r2, [msg_argc]
        BRA  error0
err_div0:
        LEA  r2, [msg_div0]
        BRA  error0
err_overflow:
        LEA  r2, [msg_overflow]
        BRA  error0

msg_error:      .asciz "error: "
s_colon:        .asciz ": "
s_nil:          .asciz "nil"
s_eof:          .asciz "#<eof>"
s_proc:         .asciz "#<procedure>"
s_vec:          .asciz "#("
s_dot:          .asciz " . "
msg_notpair:    .asciz "not a pair"
msg_notlist:    .asciz "not a list"
msg_notnum:     .asciz "not a number"
msg_notproc:    .asciz "not a procedure"
msg_notsym:     .asciz "not a symbol"
msg_notstr:     .asciz "not a string"
msg_notvec:     .asciz "not a vector"
msg_unbound:    .asciz "unbound variable"
msg_range:      .asciz "index out of range"
msg_syntax:     .asciz "bad syntax"
msg_argc:       .asciz "wrong number of arguments"
msg_div0:       .asciz "division by zero"
msg_overflow:   .asciz "overflow"
        .align 2
