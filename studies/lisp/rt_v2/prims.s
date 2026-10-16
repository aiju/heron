; The primitives. Each is called by the calling convention (eval.s):
; r1 = the procedure, r2 = the number of arguments, r6, r5, r4, r3, r8, r0
; = the arguments (r0: a list of the 6th and later, when there are more
; than 6), r7 = the return address; it returns its result in r1. A
; primitive checks its own arguments. One that calls a routine keeps r7 on
; the stack meanwhile, and the shared exits ret_t and ret_nil return
; through r7.

TV      = S_t + 3               ; t

; ---- shared error exits: the irritant is the named register
nn6:    MOV  r1, r6
        BRA  err_notnum
nn5:    MOV  r1, r5
        BRA  err_notnum
nl6:    MOV  r1, r6
        BRA  err_notlist
ns6:    MOV  r1, r6
        BRA  err_notsym
nstr6:  MOV  r1, r6
        BRA  err_notstr
nstr5:  MOV  r1, r5
        BRA  err_notstr
nv6:    MOV  r1, r6
        BRA  err_notvec
range5: MOV  r1, r5
        BRA  err_range
ret_t:  MOV  r1, #TV
        RET
ret_nil:
        MOV  r1, r13
        RET

; args_list: the arguments (r2; r6, r5, r4, r3, r8, r0) -> r1 = a list of them.
; Keeps r0, r2-r6, r8-r10.
args_list:
        PUSH r7
        MOV  r12, r13
        CMP  r2, #6
        BLS  .k
        MOV  r12, r0            ; the arguments after the fifth are a list already
        BRA  .a5
.k:     CMP  r2, #6
        BEQ  .a6
        CMP  r2, #5
        BEQ  .a5
        CMP  r2, #4
        BEQ  .a4
        CMP  r2, #3
        BEQ  .a3
        CMP  r2, #2
        BEQ  .a2
        CMP  r2, #1
        BEQ  .a1
        MOV  r1, r12
        JMP  [sp]+
.a6:    MOV  r11, r0
        BSR  cons_r
        MOV  r12, r1
.a5:    MOV  r11, r8
        BSR  cons_r
        MOV  r12, r1
.a4:    MOV  r11, r3
        BSR  cons_r
        MOV  r12, r1
.a3:    MOV  r11, r4
        BSR  cons_r
        MOV  r12, r1
.a2:    MOV  r11, r5
        BSR  cons_r
        MOV  r12, r1
.a1:    MOV  r11, r6
        POP  r7
        BRA  cons_r

; ---- pairs and lists

p_cons: CMP  r2, #2
        BNE  err_argc
        BRA  cons

p_car:  CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r6 - 1]
        RET

p_cdr:  CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r6 + 3]
        RET

p_setcar:
        CMP  r2, #2
        BNE  err_argc
        MOV  [r6 - 1], r5
        MOV  r1, r5
        RET

p_setcdr:
        CMP  r2, #2
        BNE  err_argc
        MOV  [r6 + 3], r5
        MOV  r1, r5
        RET

p_caar: CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r6 - 1]
        MOV  r1, [r1 - 1]
        RET
p_cadr: CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r6 + 3]
        MOV  r1, [r1 - 1]
        RET
p_cdar: CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r6 - 1]
        MOV  r1, [r1 + 3]
        RET
p_cddr: CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r6 + 3]
        MOV  r1, [r1 + 3]
        RET
p_caddr:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r6 + 3]
        MOV  r1, [r1 + 3]
        MOV  r1, [r1 - 1]
        RET
p_cdddr:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r6 + 3]
        MOV  r1, [r1 + 3]
        MOV  r1, [r1 + 3]
        RET
p_cadddr:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r6 + 3]
        MOV  r1, [r1 + 3]
        MOV  r1, [r1 + 3]
        MOV  r1, [r1 - 1]
        RET

p_list: BRA  args_list

p_length:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, #0
        MOV  r5, r6
.loop:  MOV  r4, r5
        AND  r4, #3
        CMP  r4, #1
        BNE  .end
        ADD  r1, #2
        MOV  r5, [r5 + 3]
        BRA  .loop
.end:   CMP  r5, r13
        BNE  nl6
        RET

; reverse_list: r4 = a list, r5 = a tail -> r1 = the list's elements
; reversed onto the tail. r3 = the list again, for errors. Uses r4-r6.
reverse_list:
        PUSH r7
.loop:  MOV  r6, r4
        AND  r6, #3
        CMP  r6, #1
        BNE  .end
        MOV  r6, [r4 - 1]
        MOV  r4, [r4 + 3]
        BSR  cons
        MOV  r5, r1
        BRA  .loop
.end:   CMP  r4, r13
        BNE  .bad
        MOV  r1, r5
        JMP  [sp]+
.bad:   MOV  r1, r3
        BRA  err_notlist

p_reverse:
        CMP  r2, #1
        BNE  err_argc
        MOV  r4, r6
        MOV  r3, r6
        MOV  r5, r13
        BRA  reverse_list

p_append:
        CMP  r2, #0
        BEQ  ret_nil
        PUSH r7
        BSR  args_list          ; (l1 ... ln)
        MOV  r4, r1
        MOV  r3, r1
        MOV  r5, r13
        BSR  reverse_list       ; (ln ... l1)
        MOV  r0, [r1 + 3]       ; the lists to copy, last first
        MOV  r8, [r1 - 1]       ; the result so far: ln
.next:  CMP  r0, r13
        BEQ  .done
        MOV  r4, [r0 - 1]       ; a list to copy onto the result
        MOV  r3, r4
        MOV  r5, r13
        BSR  reverse_list
        MOV  r4, r1
        MOV  r5, r8
        MOV  r3, r4
        BSR  reverse_list
        MOV  r8, r1
        MOV  r0, [r0 + 3]
        BRA  .next
.done:  MOV  r1, r8
        JMP  [sp]+

p_memq: CMP  r2, #2
        BNE  err_argc
        MOV  r4, r5
.loop:  MOV  r3, r4
        AND  r3, #3
        CMP  r3, #1
        BNE  .end
        CMP  r6, [r4 - 1]
        BEQ  .found
        MOV  r4, [r4 + 3]
        BRA  .loop
.found: MOV  r1, r4
        RET
.end:   CMP  r4, r13
        BEQ  ret_nil
        MOV  r1, r5             ; a dotted list
        BRA  err_notlist

p_assq: CMP  r2, #2
        BNE  err_argc
        MOV  r4, r5
.loop:  MOV  r3, r4
        AND  r3, #3
        CMP  r3, #1
        BNE  .end
        MOV  r1, [r4 - 1]       ; (an element that isn't a pair traps: not a pair)
        CMP  r6, [r1 - 1]
        BEQ  .found
        MOV  r4, [r4 + 3]
        BRA  .loop
.found: RET
.end:   CMP  r4, r13
        BEQ  ret_nil
        MOV  r1, r5
        BRA  err_notlist

; ---- predicates

p_eq:   CMP  r2, #2
        BNE  err_argc
        CMP  r6, r5
        BEQ  ret_t
        BRA  ret_nil

p_not:  CMP  r2, #1
        BNE  err_argc
        CMP  r6, r13
        BEQ  ret_t
        BRA  ret_nil

p_pairp:
        CMP  r2, #1
        BNE  err_argc
        AND  r6, #3
        CMP  r6, #1
        BEQ  ret_t
        BRA  ret_nil

p_atomp:
        CMP  r2, #1
        BNE  err_argc
        AND  r6, #3
        CMP  r6, #1
        BNE  ret_t
        BRA  ret_nil

p_numberp:
        CMP  r2, #1
        BNE  err_argc
        AND  r6, #1
        BEQ  ret_t
        BRA  ret_nil

p_eofp: CMP  r2, #1
        BNE  err_argc
        CMP  r6, #EOFV
        BEQ  ret_t
        BRA  ret_nil

p_symbolp:
        CMP  r2, #1
        BNE  err_argc
        MOV  r9, r6
        PUSH r7
        BSR  is_sym
        POP  r7
        BEQ  ret_t
        BRA  ret_nil

; type_byte: r6 = a value -> r1 = its header's low byte, or 0 if it isn't
; an object (nil counts as one).
type_byte:
        MOV  r1, r6
        AND  r1, #3
        CMP  r1, #3
        BNE  .no
        MOV  r1, byte [r6 - 3]
        RET
.no:    MOV  r1, #0
        RET

p_stringp:
        CMP  r2, #1
        BNE  err_argc
        PUSH r7
        BSR  type_byte
        POP  r7
        CMP  r1, #B_STR
        BEQ  ret_t
        BRA  ret_nil

p_vectorp:
        CMP  r2, #1
        BNE  err_argc
        PUSH r7
        BSR  type_byte
        POP  r7
        CMP  r1, #B_VEC
        BEQ  ret_t
        BRA  ret_nil

p_procp:
        CMP  r2, #1
        BNE  err_argc
        PUSH r7
        BSR  is_proc
        POP  r7
        BEQ  ret_t
        BRA  ret_nil


p_equal:
        CMP  r2, #2
        BNE  err_argc
        PUSH r7
        BSR  equal
        POP  r7
        BEQ  ret_t
        BRA  ret_nil

; equal: r6, r5 -> Z set if they're equal?. Uses r1, r4-r6, r9-r11.
equal:  PUSH r7
        CMP  sp, [stack_limit]
        BLO  err_stack
.loop:  CMP  r6, r5
        BEQ  .ret
        MOV  r1, r6
        AND  r1, #3
        CMP  r1, #1
        BNE  .atom
        MOV  r1, r5
        AND  r1, #3
        CMP  r1, #1
        BNE  .ret               ; (Z is clear)
        PUSH r6                 ; two pairs: the cars, then loop on the cdrs
        PUSH r5
        MOV  r6, [r6 - 1]
        MOV  r5, [r5 - 1]
        BSR  equal
        BNE  .ne
        POP  r5
        POP  r6
        MOV  r6, [r6 + 3]
        MOV  r5, [r5 + 3]
        BRA  .loop
.ne:    ADD  sp, #8             ; (Z clear: sp isn't 0)
        JMP  [sp]+
.atom:  BSR  type_byte          ; strings with the same bytes?
        CMP  r1, #B_STR
        BNE  .ret
        MOV  r4, r6
        MOV  r6, r5
        BSR  type_byte
        MOV  r6, r4
        CMP  r1, #B_STR
        BNE  .ret
        POP  r7
        BRA  str_eq
.ret:   JMP  [sp]+

; str_eq: r6, r5 = strings -> Z set if their bytes are the same.
str_eq: MOV  r4, [r6 - 3]
        CMP  r4, [r5 - 3]
        BNE  .ret
        LSR  r4, #8
        LEA  r9, [r6 + STR_BYTES]
        LEA  r10, [r5 + STR_BYTES]
.loop:  SUB  r4, #1
        BLO  .same
        MOV  r11, byte [r9]+
        CMP  r11, byte [r10]+
        BEQ  .loop
        RET
.same:  CMP  r4, r4
.ret:   RET

; ---- arithmetic

p_add:  CMP  r2, #2
        BNE  .gen
        MOV  r1, r6
.if tagged
        TADD r1, r5             ; traps unless both are integers and the sum fits
.else
        TST  r6, #1
        BNE  nn6
        TST  r5, #1
        BNE  nn5
        ADD  r1, r5
        BVS  err_overflow
.endif
        RET
.gen:   PUSH r7
        BSR  args_list
        MOV  r5, r1
        MOV  r1, #0
.loop:  CMP  r5, r13
        BEQ  .done
        MOV  r6, [r5 - 1]
.if tagged
        TADD r1, r6
.else
        TST  r6, #1
        BNE  nn6
        ADD  r1, r6
        BVS  err_overflow
.endif
        MOV  r5, [r5 + 3]
        BRA  .loop
.done:  JMP  [sp]+

p_sub:  CMP  r2, #2
        BNE  .gen
        MOV  r1, r6
.if tagged
        TSUB r1, r5
.else
        TST  r6, #1
        BNE  nn6
        TST  r5, #1
        BNE  nn5
        SUB  r1, r5
        BVS  err_overflow
.endif
        RET
.gen:   CMP  r2, #1
        BLO  err_argc
        BNE  .many
.if tagged                      ; (- n)
        TTST r6, r6
.else
        TST  r6, #1
        BNE  nn6
.endif
        NEG  r1, r6
        BVS  err_overflow
        RET
.many:  PUSH r7
        BSR  args_list
        MOV  r6, [r1 - 1]
.if tagged
        TTST r6, r6
.else
        TST  r6, #1
        BNE  nn6
.endif
        MOV  r5, [r1 + 3]
        MOV  r1, r6
.loop:  CMP  r5, r13
        BEQ  .done
        MOV  r6, [r5 - 1]
.if tagged
        TSUB r1, r6
.else
        TST  r6, #1
        BNE  nn6
        SUB  r1, r6
        BVS  err_overflow
.endif
        MOV  r5, [r5 + 3]
        BRA  .loop
.done:  JMP  [sp]+

p_mul:  CMP  r2, #2
        BNE  .gen
.if tagged
        TTST r6, r5
.else
        TST  r6, #1
        BNE  nn6
        TST  r5, #1
        BNE  nn5
.endif
        MOV  r1, r6
        ASR  r1, #1
        MULS r0:r1, r5
        BVS  err_overflow
        RET
.gen:   PUSH r7
        BSR  args_list
        MOV  r5, r1
        MOV  r1, #2             ; 1
.loop:  CMP  r5, r13
        BEQ  .done
        MOV  r6, [r5 - 1]
.if tagged
        TTST r6, r6
.else
        TST  r6, #1
        BNE  nn6
.endif
        ASR  r1, #1
        MULS r0:r1, r6
        BVS  err_overflow
        MOV  r5, [r5 + 3]
        BRA  .loop
.done:  JMP  [sp]+

; div_args: check quotient's and friends' arguments.
div_args:
        CMP  r2, #2
        BNE  err_argc
.if tagged
        TTST r6, r5
.else
        TST  r6, #1
        BNE  nn6
        TST  r5, #1
        BNE  nn5
.endif
        CMP  r5, #0
        BEQ  err_div0
        MOV  r1, r6
        RET

p_quotient:
        PUSH r7
        BSR  div_args
        POP  r7
        DIVS r0:r1, r5          ; 2a / 2b = a / b
        ADD  r1, r1
        BVS  err_overflow
        RET

p_remainder:
        PUSH r7
        BSR  div_args
        POP  r7
        DIVS r0:r1, r5
        MOV  r1, r0             ; 2a rem 2b = 2 (a rem b)
        RET

p_modulo:
        PUSH r7
        BSR  div_args
        POP  r7
        DIVS r0:r1, r5
        MOV  r1, r0             ; the remainder
        CMP  r1, #0
        BEQ  .done
        MOV  r2, r1
        XOR  r2, r5
        BPL  .done
        ADD  r1, r5
.done:  RET

; num2: check two number arguments, then compare them.
num2:   CMP  r2, #2
        BNE  err_argc
.if tagged
        TCMP r6, r5
.else
        TST  r6, #1
        BNE  nn6
        TST  r5, #1
        BNE  nn5
        CMP  r6, r5
.endif
        RET

p_numeq:
        PUSH r7
        BSR  num2
        POP  r7
        BEQ  ret_t
        BRA  ret_nil
p_lt:   PUSH r7
        BSR  num2
        POP  r7
        BLT  ret_t
        BRA  ret_nil
p_gt:   PUSH r7
        BSR  num2
        POP  r7
        BGT  ret_t
        BRA  ret_nil
p_le:   PUSH r7
        BSR  num2
        POP  r7
        BLE  ret_t
        BRA  ret_nil
p_ge:   PUSH r7
        BSR  num2
        POP  r7
        BGE  ret_t
        BRA  ret_nil

p_zerop:
        CMP  r2, #1
        BNE  err_argc
.if tagged
        TTST r6, r6
.else
        TST  r6, #1
        BNE  nn6
        CMP  r6, #0
.endif
        BEQ  ret_t
        BRA  ret_nil

p_logand:
        PUSH r7
        BSR  num2
        POP  r7
        MOV  r1, r6
        AND  r1, r5
        RET
p_logior:
        PUSH r7
        BSR  num2
        POP  r7
        MOV  r1, r6
        OR   r1, r5
        RET
p_logxor:
        PUSH r7
        BSR  num2
        POP  r7
        MOV  r1, r6
        XOR  r1, r5
        RET

p_ash:  PUSH r7
        BSR  num2
        POP  r7
        MOV  r4, r5
        ASR  r4, #1             ; k
        BMI  .right
        MOV  r1, r6
        CMP  r4, #31
        BHS  .big
        LSL  r1, r4
        MOV  r3, r1
        ASR  r3, r4
        CMP  r3, r6
        BNE  err_overflow
        RET
.big:   CMP  r6, #0
        BNE  err_overflow
        MOV  r1, #0
        RET
.right: NEG  r4, r4
        CMP  r4, #31
        BLS  .sh
        MOV  r4, #31
.sh:    MOV  r1, r6
        ASR  r1, r4
        AND  r1, #-2
        RET

; ---- symbols and strings

p_gensym:
        CMP  r2, #0
        BNE  err_argc
        PUSH r7
        INC  [gensym_n]
        MOV  r1, [gensym_n]
        MOV  r9, #tokbuf + 32   ; its digits, backwards
        MOV  r5, #10
.dig:   DIVU r0:r1, r5
        MOV  r2, r0
        ADD  r2, #'0'
        SUB  r9, #1
        MOV  byte [r9], r2
        CMP  r1, #0
        BNE  .dig
        SUB  r9, #1
        MOV  r2, #'g'
        MOV  byte [r9], r2
        MOV  r1, #tokbuf + 32
        SUB  r1, r9
        MOV  r2, r9
        BSR  make_string
        MOV  r4, r1
        MOV  r2, #32
        BSR  alloc
        MOV  r3, #H_SYM
        MOV  [r1], r3
        LEA  r3, [not_proc]
        MOV  [r1 + 4], r3
        MOV  r3, #UNB
        MOV  [r1 + 8], r3
        MOV  [r1 + 12], r4
        CLR  [r1 + 16]
        MOV  [r1 + 20], r13
        CLR  [r1 + 24]
        MOV  [r1 + 28], r13
        OR   r1, #3
        JMP  [sp]+

p_sym2str:
        CMP  r2, #1
        BNE  err_argc
        MOV  r9, r6
        PUSH r7
        BSR  is_sym
        POP  r7
        BNE  ns6
        MOV  r1, [r6 + SYM_NAME]
        RET

; is_str: r6 -> Z set if it's a string. Uses r1.
is_str: PUSH r7
        BSR  type_byte
        POP  r7
        CMP  r1, #B_STR
        RET

p_str2sym:
        CMP  r2, #1
        BNE  err_argc
        PUSH r7
        BSR  is_str
        POP  r7
        BNE  nstr6
        MOV  r2, [r6 - 3]       ; copy the name out of the heap, then intern it
        LSR  r2, #8
        CMP  r2, #tokbuf_end - tokbuf
        BLS  .fits
        MOV  r2, #tokbuf_end - tokbuf
.fits:  LEA  r9, [r6 + STR_BYTES]
        MOV  r10, #tokbuf
        MOV  r11, r2
.copy:  SUB  r11, #1
        BLO  .done
        MOV  r12, byte [r9]+
        MOV  byte [r10]+, r12
        BRA  .copy
.done:  MOV  r1, #tokbuf
        BRA  intern

p_strlen:
        CMP  r2, #1
        BNE  err_argc
        PUSH r7
        BSR  is_str
        POP  r7
        BNE  nstr6
        MOV  r1, [r6 - 3]
        LSR  r1, #7
        AND  r1, #-2
        RET

p_strref:
        CMP  r2, #2
        BNE  err_argc
        PUSH r7
        BSR  is_str
        POP  r7
        BNE  nstr6
        MOV  r1, r5
        AND  r1, #1
        BNE  nn5
        MOV  r1, [r6 - 3]
        LSR  r1, #7
        AND  r1, #-2            ; the length, as a fixnum
        CMP  r5, r1
        BHS  range5             ; (also catches negative indexes)
        MOV  r1, r5
        ASR  r1, #1
        MOV  r1, byte [r6 + r1 + STR_BYTES]
        ADD  r1, r1
        RET

p_streq:
        CMP  r2, #2
        BNE  err_argc
        PUSH r7
        BSR  is_str
        BNE  nstr6
        MOV  r4, r6
        MOV  r6, r5
        BSR  is_str
        BNE  nstr5
        MOV  r6, r4
        BSR  str_eq
        POP  r7
        BEQ  ret_t
        BRA  ret_nil

; plist_find: r6 = a symbol, r5 = a key -> r4 = the pair holding its
; value in the property list, or nil.
plist_find:
        MOV  r4, [r6 + SYM_PLIST]
.loop:  CMP  r4, r13
        BEQ  .ret
        MOV  r3, [r4 - 1]
        MOV  r4, [r4 + 3]
        CMP  r3, r5
        BEQ  .ret
        MOV  r4, [r4 + 3]
        BRA  .loop
.ret:   RET

p_get:  CMP  r2, #2
        BNE  err_argc
        MOV  r9, r6
        PUSH r7
        BSR  is_sym
        BNE  ns6
        BSR  plist_find
        POP  r7
        MOV  r1, r4
        CMP  r4, r13
        BEQ  .ret
        MOV  r1, [r4 - 1]
.ret:   RET

p_put:  CMP  r2, #3
        BNE  err_argc
        MOV  r9, r6
        PUSH r7
        BSR  is_sym
        BNE  ns6
        MOV  r0, r4             ; the value
        BSR  plist_find
        CMP  r4, r13
        BEQ  .new
        MOV  [r4 - 1], r0
        MOV  r1, r0
        JMP  [sp]+
.new:   MOV  r8, r6             ; (key value . plist)
        MOV  r3, r5
        MOV  r6, r0
        MOV  r5, [r8 + SYM_PLIST]
        BSR  cons
        MOV  r6, r3
        MOV  r5, r1
        BSR  cons
        MOV  [r8 + SYM_PLIST], r1
        MOV  r1, r0
        JMP  [sp]+

; ---- vectors

p_mkvec:
        CMP  r2, #2
        BNE  err_argc
        MOV  r1, r6
        AND  r1, #1
        BNE  nn6
        CMP  r6, #0
        BLT  .neg
        MOV  r2, r6             ; 8 + 4n bytes, rounded up
        ADD  r2, r6
        ADD  r2, #8 + 7
        AND  r2, #-8
        PUSH r7
        BSR  alloc
        POP  r7
        MOV  r4, r6             ; size: the elements and the call slot
        LSL  r4, #7
        ADD  r4, #1 << 8 | B_VEC
        MOV  [r1], r4
        LEA  r4, [not_proc]
        MOV  [r1 + 4], r4
        LEA  r3, [r1 + 8]
        MOV  r8, r6
.fill:  SUB  r8, #2
        BLO  .done
        MOV  [r3]+, r5
        BRA  .fill
.done:  OR   r1, #3
        RET
.neg:   MOV  r1, r6
        BRA  err_range

; vec_index: check (v k) for vector-ref and vector-set!
vec_index:
        PUSH r7
        BSR  type_byte
        POP  r7
        CMP  r1, #B_VEC
        BNE  nv6
        MOV  r1, r5
        AND  r1, #1
        BNE  nn5
        MOV  r1, [r6 - 3]
        LSR  r1, #7
        AND  r1, #-2
        SUB  r1, #2             ; the length (less the call slot), as a fixnum
        CMP  r5, r1
        BHS  range5
        RET

p_vecref:
        CMP  r2, #2
        BNE  err_argc
        PUSH r7
        BSR  vec_index
        POP  r7
        MOV  r1, [r6 + r5*2 + VEC_ELTS]
        RET

p_vecset:
        CMP  r2, #3
        BNE  err_argc
        PUSH r7
        BSR  vec_index
        POP  r7
        MOV  [r6 + r5*2 + VEC_ELTS], r4
        MOV  r1, r4
        RET

p_veclen:
        CMP  r2, #1
        BNE  err_argc
        PUSH r7
        BSR  type_byte
        POP  r7
        CMP  r1, #B_VEC
        BNE  nv6
        MOV  r1, [r6 - 3]
        LSR  r1, #7
        AND  r1, #-2
        SUB  r1, #2
        RET

; ---- control and the system

p_apply:
        CMP  r2, #2
        BNE  err_argc
        PUSH r7
        BSR  is_proc            ; the procedure first, then the list
        POP  r7
        BNE  .notproc
        MOV  r1, r6
        MOV  r2, r5
        BRA  apply_list
.notproc:
        MOV  r1, r6
        BRA  err_notproc

; is_proc: r6 -> Z set if it's a procedure. Uses r1.
is_proc:
        PUSH r7
        BSR  type_byte
        POP  r7
        CMP  r1, #B_PRIM
        BEQ  .ret
        CMP  r1, #B_CLO
        BEQ  .ret
        CMP  r1, #B_FUN
.ret:   RET

p_eval: CMP  r2, #1
        BNE  err_argc
        MOV  r1, r6
        MOV  r2, r13
        BRA  eval

p_read: CMP  r2, #0
        BNE  err_argc
        BRA  read

p_write:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, r6
        MOV  r2, #1
        PUSH r7
        BSR  print_value
        POP  r7
        BRA  ret_nil

p_display:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, r6
        MOV  r2, #0
        PUSH r7
        BSR  print_value
        POP  r7
        BRA  ret_nil

p_newline:
        CMP  r2, #0
        BNE  err_argc
        MOV  r1, #10
        PUSH r7
        BSR  putc
        POP  r7
        BRA  ret_nil

p_writechar:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, r6
        AND  r1, #1
        BNE  nn6
        MOV  r1, r6
        ASR  r1, #1
        PUSH r7
        BSR  putc
        POP  r7
        BRA  ret_nil

p_gc:   CMP  r2, #0
        BNE  err_argc
        PUSH r7
        BSR  gc
        POP  r7
        BRA  ret_nil

p_error:
        CMP  r2, #1
        BLO  err_argc
        BSR  args_list          ; (message irritant...)
        PUSH r1
        LEA  r1, [msg_error]
        BSR  puts
        MOV  r1, [sp]
        MOV  r1, [r1 - 1]
        MOV  r2, #0
        BSR  print_value
        POP  r4
        MOV  r4, [r4 + 3]
        CMP  r4, r13
        BEQ  err_end
        PUSH r4
        LEA  r1, [s_colon]
        BSR  puts
.loop:  MOV  r4, [sp]
        MOV  r1, [r4 - 1]
        MOV  r2, #1
        BSR  print_value
        MOV  r4, [sp]
        MOV  r4, [r4 + 3]
        MOV  [sp], r4
        CMP  r4, r13
        BEQ  err_end
        MOV  r1, #' '
        BSR  putc
        BRA  .loop
