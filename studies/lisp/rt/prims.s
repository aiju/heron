; The primitives. Each is called by the calling convention (eval.s):
; r1 = the procedure, r2 = the number of arguments, r3-r8 = the arguments
; (r8: a list of the 6th and later, when there are more than 6), and
; returns its result in r1. A primitive checks its own arguments.

TV      = S_t + 3               ; t

; ---- shared error exits: the irritant is the named register
nn3:    MOV  r1, r3
        BRA  err_notnum
nn4:    MOV  r1, r4
        BRA  err_notnum
nl3:    MOV  r1, r3
        BRA  err_notlist
ns3:    MOV  r1, r3
        BRA  err_notsym
nstr3:  MOV  r1, r3
        BRA  err_notstr
nstr4:  MOV  r1, r4
        BRA  err_notstr
nv3:    MOV  r1, r3
        BRA  err_notvec
range4: MOV  r1, r4
        BRA  err_range
ret_t:  MOV  r1, #TV
        RET
ret_nil:
        MOV  r1, r13
        RET

; args_list: the arguments (r2, r3-r8) -> r1 = a list of them. Keeps r2-r10.
args_list:
        MOV  r12, r13
        CMP  r2, #6
        BLS  .k
        MOV  r12, r8
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
        RET
.a6:    MOV  r11, r8
        BSR  cons_r
        MOV  r12, r1
.a5:    MOV  r11, r7
        BSR  cons_r
        MOV  r12, r1
.a4:    MOV  r11, r6
        BSR  cons_r
        MOV  r12, r1
.a3:    MOV  r11, r5
        BSR  cons_r
        MOV  r12, r1
.a2:    MOV  r11, r4
        BSR  cons_r
        MOV  r12, r1
.a1:    MOV  r11, r3
        BRA  cons_r

; ---- pairs and lists

p_cons: CMP  r2, #2
        BNE  err_argc
        BRA  cons

p_car:  CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r3 - 1]
        RET

p_cdr:  CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r3 + 3]
        RET

p_setcar:
        CMP  r2, #2
        BNE  err_argc
        ST   r4, [r3 - 1]
        MOV  r1, r4
        RET

p_setcdr:
        CMP  r2, #2
        BNE  err_argc
        ST   r4, [r3 + 3]
        MOV  r1, r4
        RET

p_caar: CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r3 - 1]
        MOV  r1, [r1 - 1]
        RET
p_cadr: CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r3 + 3]
        MOV  r1, [r1 - 1]
        RET
p_cdar: CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r3 - 1]
        MOV  r1, [r1 + 3]
        RET
p_cddr: CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r3 + 3]
        MOV  r1, [r1 + 3]
        RET
p_caddr:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r3 + 3]
        MOV  r1, [r1 + 3]
        MOV  r1, [r1 - 1]
        RET
p_cdddr:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r3 + 3]
        MOV  r1, [r1 + 3]
        MOV  r1, [r1 + 3]
        RET
p_cadddr:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, [r3 + 3]
        MOV  r1, [r1 + 3]
        MOV  r1, [r1 + 3]
        MOV  r1, [r1 - 1]
        RET

p_list: BRA  args_list

p_length:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, #0
        MOV  r4, r3
.loop:  MOV  r5, r4
        AND  r5, #3
        CMP  r5, #1
        BNE  .end
        ADD  r1, #2
        MOV  r4, [r4 + 3]
        BRA  .loop
.end:   CMP  r4, r13
        BNE  nl3
        RET

; reverse_list: r5 = a list, r4 = a tail -> r1 = the list's elements
; reversed onto the tail. r6 = the list again, for errors. Uses r3-r5.
reverse_list:
.loop:  MOV  r3, r5
        AND  r3, #3
        CMP  r3, #1
        BNE  .end
        MOV  r3, [r5 - 1]
        MOV  r5, [r5 + 3]
        BSR  cons
        MOV  r4, r1
        BRA  .loop
.end:   CMP  r5, r13
        BNE  .bad
        MOV  r1, r4
        RET
.bad:   MOV  r1, r6
        BRA  err_notlist

p_reverse:
        CMP  r2, #1
        BNE  err_argc
        MOV  r5, r3
        MOV  r6, r3
        MOV  r4, r13
        BRA  reverse_list

p_append:
        CMP  r2, #0
        BEQ  ret_nil
        BSR  args_list          ; (l1 ... ln)
        MOV  r5, r1
        MOV  r6, r1
        MOV  r4, r13
        BSR  reverse_list       ; (ln ... l1)
        MOV  r7, [r1 + 3]       ; the lists to copy, last first
        MOV  r8, [r1 - 1]       ; the result so far: ln
.next:  CMP  r7, r13
        BEQ  .done
        MOV  r5, [r7 - 1]       ; a list to copy onto the result
        MOV  r6, r5
        MOV  r4, r13
        BSR  reverse_list
        MOV  r5, r1
        MOV  r4, r8
        MOV  r6, r5
        BSR  reverse_list
        MOV  r8, r1
        MOV  r7, [r7 + 3]
        BRA  .next
.done:  MOV  r1, r8
        RET

p_memq: CMP  r2, #2
        BNE  err_argc
        MOV  r5, r4
.loop:  MOV  r6, r5
        AND  r6, #3
        CMP  r6, #1
        BNE  .end
        CMP  r3, [r5 - 1]
        BEQ  .found
        MOV  r5, [r5 + 3]
        BRA  .loop
.found: MOV  r1, r5
        RET
.end:   CMP  r5, r13
        BEQ  ret_nil
        MOV  r1, r4             ; a dotted list
        BRA  err_notlist

p_assq: CMP  r2, #2
        BNE  err_argc
        MOV  r5, r4
.loop:  MOV  r6, r5
        AND  r6, #3
        CMP  r6, #1
        BNE  .end
        MOV  r1, [r5 - 1]       ; (an element that isn't a pair traps: not a pair)
        CMP  r3, [r1 - 1]
        BEQ  .found
        MOV  r5, [r5 + 3]
        BRA  .loop
.found: RET
.end:   CMP  r5, r13
        BEQ  ret_nil
        MOV  r1, r4
        BRA  err_notlist

; ---- predicates

p_eq:   CMP  r2, #2
        BNE  err_argc
        CMP  r3, r4
        BEQ  ret_t
        BRA  ret_nil

p_not:  CMP  r2, #1
        BNE  err_argc
        CMP  r3, r13
        BEQ  ret_t
        BRA  ret_nil

p_pairp:
        CMP  r2, #1
        BNE  err_argc
        AND  r3, #3
        CMP  r3, #1
        BEQ  ret_t
        BRA  ret_nil

p_atomp:
        CMP  r2, #1
        BNE  err_argc
        AND  r3, #3
        CMP  r3, #1
        BNE  ret_t
        BRA  ret_nil

p_numberp:
        CMP  r2, #1
        BNE  err_argc
        AND  r3, #1
        BEQ  ret_t
        BRA  ret_nil

p_eofp: CMP  r2, #1
        BNE  err_argc
        CMP  r3, #EOFV
        BEQ  ret_t
        BRA  ret_nil

p_symbolp:
        CMP  r2, #1
        BNE  err_argc
        MOV  r9, r3
        BSR  is_sym
        BEQ  ret_t
        BRA  ret_nil

; type_byte: r3 = a value -> r1 = its header's low byte, or 0 if it isn't
; an object (nil counts as one).
type_byte:
        MOV  r1, r3
        AND  r1, #3
        CMP  r1, #3
        BNE  .no
        MOV  r1, byte [r3 - 3]
        RET
.no:    MOV  r1, #0
        RET

p_stringp:
        CMP  r2, #1
        BNE  err_argc
        BSR  type_byte
        CMP  r1, #B_STR
        BEQ  ret_t
        BRA  ret_nil

p_vectorp:
        CMP  r2, #1
        BNE  err_argc
        BSR  type_byte
        CMP  r1, #B_VEC
        BEQ  ret_t
        BRA  ret_nil

p_procp:
        CMP  r2, #1
        BNE  err_argc
        BSR  is_proc
        BEQ  ret_t
        BRA  ret_nil


p_equal:
        CMP  r2, #2
        BNE  err_argc
        BSR  equal
        BEQ  ret_t
        BRA  ret_nil

; equal: r3, r4 -> Z set if they're equal?. Uses r1, r3-r5, r9-r11.
equal:  CMP  sp, [stack_limit]
        BLO  err_stack
.loop:  CMP  r3, r4
        BEQ  .ret
        MOV  r1, r3
        AND  r1, #3
        CMP  r1, #1
        BNE  .atom
        MOV  r1, r4
        AND  r1, #3
        CMP  r1, #1
        BNE  .ret               ; (Z is clear)
        PUSH r3                 ; two pairs: the cars, then loop on the cdrs
        PUSH r4
        MOV  r3, [r3 - 1]
        MOV  r4, [r4 - 1]
        BSR  equal
        BNE  .ne
        POP  r4                 ; (POP sets the flags: test first)
        POP  r3
        MOV  r3, [r3 + 3]
        MOV  r4, [r4 + 3]
        BRA  .loop
.ne:    ADD  sp, #8             ; (Z clear: sp isn't 0)
        RET
.atom:  BSR  type_byte          ; strings with the same bytes?
        CMP  r1, #B_STR
        BNE  .ret
        MOV  r5, r3
        MOV  r3, r4
        BSR  type_byte
        MOV  r3, r5
        CMP  r1, #B_STR
        BNE  .ret
        BRA  str_eq
.ret:   RET

; str_eq: r3, r4 = strings -> Z set if their bytes are the same.
str_eq: MOV  r5, [r3 - 3]
        CMP  r5, [r4 - 3]
        BNE  .ret
        LSR  r5, #8
        LEA  r9, [r3 + STR_BYTES]
        LEA  r10, [r4 + STR_BYTES]
.loop:  SUB  r5, #1
        BLO  .same
        MOV  r11, byte [r9]+
        CMP  r11, byte [r10]+
        BEQ  .loop
        RET
.same:  CMP  r5, r5
.ret:   RET

; ---- arithmetic

p_add:  CMP  r2, #2
        BNE  .gen
        MOV  r1, r3
        AND  r1, #1
        BNE  nn3
        MOV  r1, r4
        AND  r1, #1
        BNE  nn4
        MOV  r1, r3
        ADD  r1, r4
        BVS  err_overflow
        RET
.gen:   BSR  args_list
        MOV  r4, r1
        MOV  r1, #0
.loop:  CMP  r4, r13
        BEQ  .done
        MOV  r3, [r4 - 1]
        MOV  r5, r3
        AND  r5, #1
        BNE  nn3
        ADD  r1, r3
        BVS  err_overflow
        MOV  r4, [r4 + 3]
        BRA  .loop
.done:  RET

p_sub:  CMP  r2, #2
        BNE  .gen
        MOV  r1, r3
        AND  r1, #1
        BNE  nn3
        MOV  r1, r4
        AND  r1, #1
        BNE  nn4
        MOV  r1, r3
        SUB  r1, r4
        BVS  err_overflow
        RET
.gen:   CMP  r2, #1
        BLO  err_argc
        BNE  .many
        MOV  r1, r3             ; (- n)
        AND  r1, #1
        BNE  nn3
        NEG  r1, r3
        BVS  err_overflow
        RET
.many:  BSR  args_list
        MOV  r3, [r1 - 1]
        MOV  r5, r3
        AND  r5, #1
        BNE  nn3
        MOV  r4, [r1 + 3]
        MOV  r1, r3
.loop:  CMP  r4, r13
        BEQ  .done
        MOV  r3, [r4 - 1]
        MOV  r5, r3
        AND  r5, #1
        BNE  nn3
        SUB  r1, r3
        BVS  err_overflow
        MOV  r4, [r4 + 3]
        BRA  .loop
.done:  RET

p_mul:  CMP  r2, #2
        BNE  .gen
        MOV  r1, r3
        AND  r1, #1
        BNE  nn3
        MOV  r1, r4
        AND  r1, #1
        BNE  nn4
        MOV  r1, r3
        ASR  r1, #1
        MULS r1, r4
        BVS  err_overflow
        RET
.gen:   BSR  args_list
        MOV  r4, r1
        MOV  r1, #2             ; 1
.loop:  CMP  r4, r13
        BEQ  .done
        MOV  r3, [r4 - 1]
        MOV  r5, r3
        AND  r5, #1
        BNE  nn3
        ASR  r1, #1
        MULS r1, r3
        BVS  err_overflow
        MOV  r4, [r4 + 3]
        BRA  .loop
.done:  RET

; div_args: check quotient's and friends' arguments.
div_args:
        CMP  r2, #2
        BNE  err_argc
        MOV  r1, r3
        AND  r1, #1
        BNE  nn3
        MOV  r1, r4
        AND  r1, #1
        BNE  nn4
        CMP  r4, #0
        BEQ  err_div0
        MOV  r1, r3
        RET

p_quotient:
        BSR  div_args
        DIVS r1, r4             ; 2a / 2b = a / b
        ADD  r1, r1
        BVS  err_overflow
        RET

p_remainder:
        BSR  div_args
        DIVS r1, r4
        MFHI r1                 ; 2a rem 2b = 2 (a rem b)
        RET

p_modulo:
        BSR  div_args
        DIVS r1, r4
        MFHI r1
        CMP  r1, #0
        BEQ  .done
        MOV  r2, r1
        XOR  r2, r4
        BPL  .done
        ADD  r1, r4
.done:  RET

; num2: check two number arguments, then compare them.
num2:   CMP  r2, #2
        BNE  err_argc
        MOV  r1, r3
        AND  r1, #1
        BNE  nn3
        MOV  r1, r4
        AND  r1, #1
        BNE  nn4
        CMP  r3, r4
        RET

p_numeq:
        BSR  num2
        BEQ  ret_t
        BRA  ret_nil
p_lt:   BSR  num2
        BLT  ret_t
        BRA  ret_nil
p_gt:   BSR  num2
        BGT  ret_t
        BRA  ret_nil
p_le:   BSR  num2
        BLE  ret_t
        BRA  ret_nil
p_ge:   BSR  num2
        BGE  ret_t
        BRA  ret_nil

p_zerop:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, r3
        AND  r1, #1
        BNE  nn3
        CMP  r3, #0
        BEQ  ret_t
        BRA  ret_nil

p_logand:
        BSR  num2
        MOV  r1, r3
        AND  r1, r4
        RET
p_logior:
        BSR  num2
        MOV  r1, r3
        OR   r1, r4
        RET
p_logxor:
        BSR  num2
        MOV  r1, r3
        XOR  r1, r4
        RET

p_ash:  BSR  num2
        MOV  r5, r4
        ASR  r5, #1             ; k
        BMI  .right
        MOV  r1, r3
        CMP  r5, #31
        BHS  .big
        LSL  r1, r5
        MOV  r6, r1
        ASR  r6, r5
        CMP  r6, r3
        BNE  err_overflow
        RET
.big:   CMP  r3, #0
        BNE  err_overflow
        MOV  r1, #0
        RET
.right: NEG  r5, r5
        CMP  r5, #31
        BLS  .sh
        MOV  r5, #31
.sh:    MOV  r1, r3
        ASR  r1, r5
        AND  r1, #-2
        RET

; ---- symbols and strings

p_gensym:
        CMP  r2, #0
        BNE  err_argc
        MOV  r1, [gensym_n]
        INC  r1
        ST   r1, [gensym_n]
        MOV  r9, #tokbuf + 32   ; its digits, backwards
        MOV  r4, #10
.dig:   DIVU r1, r4
        MFHI r2
        ADD  r2, #'0'
        SUB  r9, #1
        ST   r2, byte [r9]
        CMP  r1, #0
        BNE  .dig
        SUB  r9, #1
        MOV  r2, #'g'
        ST   r2, byte [r9]
        MOV  r1, #tokbuf + 32
        SUB  r1, r9
        MOV  r2, r9
        BSR  make_string
        MOV  r5, r1
        MOV  r2, #32
        BSR  alloc
        MOV  r6, #H_SYM
        ST   r6, [r1]
        LEA  r6, [not_proc]
        ST   r6, [r1 + 4]
        MOV  r6, #UNB
        ST   r6, [r1 + 8]
        ST   r5, [r1 + 12]
        ST   r0, [r1 + 16]
        ST   r13, [r1 + 20]
        ST   r0, [r1 + 24]
        ST   r13, [r1 + 28]
        OR   r1, #3
        RET

p_sym2str:
        CMP  r2, #1
        BNE  err_argc
        MOV  r9, r3
        BSR  is_sym
        BNE  ns3
        MOV  r1, [r3 + SYM_NAME]
        RET

; is_str: r3 -> Z set if it's a string. Uses r1.
is_str: BSR  type_byte
        CMP  r1, #B_STR
        RET

p_str2sym:
        CMP  r2, #1
        BNE  err_argc
        BSR  is_str
        BNE  nstr3
        MOV  r2, [r3 - 3]       ; copy the name out of the heap, then intern it
        LSR  r2, #8
        CMP  r2, #tokbuf_end - tokbuf
        BLS  .fits
        MOV  r2, #tokbuf_end - tokbuf
.fits:  LEA  r9, [r3 + STR_BYTES]
        MOV  r10, #tokbuf
        MOV  r11, r2
.copy:  SUB  r11, #1
        BLO  .done
        MOV  r12, byte [r9]+
        ST   r12, byte [r10]+
        BRA  .copy
.done:  MOV  r1, #tokbuf
        BRA  intern

p_strlen:
        CMP  r2, #1
        BNE  err_argc
        BSR  is_str
        BNE  nstr3
        MOV  r1, [r3 - 3]
        LSR  r1, #7
        AND  r1, #-2
        RET

p_strref:
        CMP  r2, #2
        BNE  err_argc
        BSR  is_str
        BNE  nstr3
        MOV  r1, r4
        AND  r1, #1
        BNE  nn4
        MOV  r1, [r3 - 3]
        LSR  r1, #7
        AND  r1, #-2            ; the length, as a fixnum
        CMP  r4, r1
        BHS  range4             ; (also catches negative indexes)
        MOV  r1, r4
        ASR  r1, #1
        MOV  r1, byte [r3 + r1 + STR_BYTES]
        ADD  r1, r1
        RET

p_streq:
        CMP  r2, #2
        BNE  err_argc
        BSR  is_str
        BNE  nstr3
        MOV  r5, r3
        MOV  r3, r4
        BSR  is_str
        BNE  nstr4
        MOV  r3, r5
        BSR  str_eq
        BEQ  ret_t
        BRA  ret_nil

; plist_find: r3 = a symbol, r4 = a key -> r5 = the pair holding its
; value in the property list, or nil.
plist_find:
        MOV  r5, [r3 + SYM_PLIST]
.loop:  CMP  r5, r13
        BEQ  .ret
        MOV  r6, [r5 - 1]
        MOV  r5, [r5 + 3]
        CMP  r6, r4
        BEQ  .ret
        MOV  r5, [r5 + 3]
        BRA  .loop
.ret:   RET

p_get:  CMP  r2, #2
        BNE  err_argc
        MOV  r9, r3
        BSR  is_sym
        BNE  ns3
        BSR  plist_find
        MOV  r1, r5
        CMP  r5, r13
        BEQ  .ret
        MOV  r1, [r5 - 1]
.ret:   RET

p_put:  CMP  r2, #3
        BNE  err_argc
        MOV  r9, r3
        BSR  is_sym
        BNE  ns3
        MOV  r7, r5             ; the value
        BSR  plist_find
        CMP  r5, r13
        BEQ  .new
        ST   r7, [r5 - 1]
        MOV  r1, r7
        RET
.new:   MOV  r8, r3             ; (key value . plist)
        MOV  r6, r4
        MOV  r3, r7
        MOV  r4, [r8 + SYM_PLIST]
        BSR  cons
        MOV  r3, r6
        MOV  r4, r1
        BSR  cons
        ST   r1, [r8 + SYM_PLIST]
        MOV  r1, r7
        RET

; ---- vectors

p_mkvec:
        CMP  r2, #2
        BNE  err_argc
        MOV  r1, r3
        AND  r1, #1
        BNE  nn3
        CMP  r3, #0
        BLT  .neg
        MOV  r2, r3             ; 8 + 4n bytes, rounded up
        ADD  r2, r3
        ADD  r2, #8 + 7
        AND  r2, #-8
        BSR  alloc
        MOV  r5, r3
        LSL  r5, #7
        OR   r5, #B_VEC
        ST   r5, [r1]
        LEA  r5, [not_proc]
        ST   r5, [r1 + 4]
        LEA  r6, [r1 + 8]
        MOV  r7, r3
.fill:  SUB  r7, #2
        BLO  .done
        ST   r4, [r6]+
        BRA  .fill
.done:  OR   r1, #3
        RET
.neg:   MOV  r1, r3
        BRA  err_range

; vec_index: check (v k) for vector-ref and vector-set!
vec_index:
        BSR  type_byte
        CMP  r1, #B_VEC
        BNE  nv3
        MOV  r1, r4
        AND  r1, #1
        BNE  nn4
        MOV  r1, [r3 - 3]
        LSR  r1, #7
        AND  r1, #-2            ; the length, as a fixnum
        CMP  r4, r1
        BHS  range4
        RET

p_vecref:
        CMP  r2, #2
        BNE  err_argc
        BSR  vec_index
        MOV  r1, [r3 + r4*2 + VEC_ELTS]
        RET

p_vecset:
        CMP  r2, #3
        BNE  err_argc
        BSR  vec_index
        ST   r5, [r3 + r4*2 + VEC_ELTS]
        MOV  r1, r5
        RET

p_veclen:
        CMP  r2, #1
        BNE  err_argc
        BSR  type_byte
        CMP  r1, #B_VEC
        BNE  nv3
        MOV  r1, [r3 - 3]
        LSR  r1, #7
        AND  r1, #-2
        RET

; ---- control and the system

p_apply:
        CMP  r2, #2
        BNE  err_argc
        BSR  is_proc            ; the procedure first, then the list
        BNE  .notproc
        MOV  r1, r3
        MOV  r2, r4
        BRA  apply_list
.notproc:
        MOV  r1, r3
        BRA  err_notproc

; is_proc: r3 -> Z set if it's a procedure. Uses r1.
is_proc:
        BSR  type_byte
        CMP  r1, #B_PRIM
        BEQ  .ret
        CMP  r1, #B_CLO
        BEQ  .ret
        CMP  r1, #B_FUN
.ret:   RET

p_eval: CMP  r2, #1
        BNE  err_argc
        MOV  r1, r3
        MOV  r2, r13
        BRA  eval

p_read: CMP  r2, #0
        BNE  err_argc
        BRA  read

p_write:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, r3
        MOV  r2, #1
        BSR  print_value
        BRA  ret_nil

p_display:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, r3
        MOV  r2, #0
        BSR  print_value
        BRA  ret_nil

p_newline:
        CMP  r2, #0
        BNE  err_argc
        MOV  r1, #10
        BSR  putc
        BRA  ret_nil

p_writechar:
        CMP  r2, #1
        BNE  err_argc
        MOV  r1, r3
        AND  r1, #1
        BNE  nn3
        MOV  r1, r3
        ASR  r1, #1
        BSR  putc
        BRA  ret_nil

p_gc:   CMP  r2, #0
        BNE  err_argc
        BSR  gc
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
        POP  r5
        MOV  r5, [r5 + 3]
        CMP  r5, r13
        BEQ  err_end
        PUSH r5
        LEA  r1, [s_colon]
        BSR  puts
.loop:  MOV  r5, [sp]
        MOV  r1, [r5 - 1]
        MOV  r2, #1
        BSR  print_value
        MOV  r5, [sp]
        MOV  r5, [r5 + 3]
        ST   r5, [sp]
        CMP  r5, r13
        BEQ  err_end
        MOV  r1, #' '
        BSR  putc
        BRA  .loop
