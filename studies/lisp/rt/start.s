; The Lisp runtime for draft 1b: memory map, vectors, variables, start-up,
; the top level and the traps. implementation.md describes the design;
; this is a summary of the rules every routine keeps.
;
; Values (32 bits, the low bits are the tag):
;   ...xxx0   integer (fixnum): the value shifted left 1
;   ...x001   pair: the cell is at p - 1; car at [p - 1], cdr at [p + 3]
;   ...x011   other object: at p - 3, a header word, then a word of code
;             (the "call slot": where a call jumps to), then the fields
;   ...x101   a header word (only ever the first word of an object)
;   ...x111   a forwarding pointer (only in the old space, during a GC)
; Objects are 8-byte aligned. A word access to [p - 1] or [p + 3] is only
; aligned if p is a pair, and one to [p + 1] only if p is an other object,
; so car, cdr and calls check their argument's type for free: anything else
; is an address error, which trap_addr turns into a Lisp error.
;
; Registers:
;   r13 = nil (always), r14 = the heap's allocation pointer, r15 = sp
;   r1-r12 are free; routines say what they take and return.
;
; The garbage collector copies (Cheney). Its roots are the stack, from sp
; up, word by word; r1-r8 at the moment it runs; the symbols; and the
; root block below. A root word is updated if it looks like a pointer into
; the space being collected, and left alone otherwise. So, at any point
; that can allocate:
;   - r1-r8 and the stack must hold Lisp values, or raw values that are
;     even (return addresses always are) or don't point into the heap (an
;     odd byte address inside a string would be taken for a pointer);
;   - r9-r12 aren't roots: they keep raw values, never Lisp values;
;   - no untagged pointer into the heap may be kept, since objects move.

; ---- memory map
SYM_BASE    = 0x0410            ; symbol space: the static symbols, then new ones
SYM_END     = 0x8000
CONST_BASE  = 0x18000           ; constant space: names of new symbols, compiled constants
CONST_END   = 0x20000
CCODE_BASE  = 0x20000           ; compiled code
CCODE_END   = 0x38000
HEAP_A      = 0x38000           ; the two halves of the heap
HEAP_B      = 0x94000
HEAP_SIZE   = 0x5C000
STACK_TOP   = 0x100000
STACK_LIMIT = 0xF0800           ; below this, eval reports a stack overflow

; ---- object types and headers: size << 8 | type << 3 | 5
T_SYM   = 0                     ; [hdr][call][value][name][special][macro][next][plist]
T_STR   = 1                     ; [hdr][call][bytes...]; size = bytes
T_VEC   = 2                     ; [hdr][call][elements...]
T_PRIM  = 3                     ; [hdr][code][name][0]
T_CLO   = 4                     ; compiled closure: [hdr][code][free variables...]
T_FUN   = 5                     ; interpreted closure: [hdr][interp_entry][params][body][env][shape]
T_FRAME = 6                     ; environment: [hdr][parent][name][value]...
T_NIL   = 7                     ; nil: [hdr][call]
T_EOF   = 8                     ; the end-of-file object: [hdr][call]

H_SYM   = 7 << 8 | T_SYM << 3 | 5
H_PRIM  = 3 << 8 | T_PRIM << 3 | 5
H_FUN   = 5 << 8 | T_FUN << 3 | 5
B_SYM   = T_SYM << 3 | 5        ; the low byte of each type's header
B_STR   = T_STR << 3 | 5
B_VEC   = T_VEC << 3 | 5
B_PRIM  = T_PRIM << 3 | 5
B_CLO   = T_CLO << 3 | 5
B_FUN   = T_FUN << 3 | 5
B_FRAME = T_FRAME << 3 | 5

; field offsets from a tagged pointer
SYM_VALUE   = 5
SYM_NAME    = 9
SYM_SPECIAL = 13
SYM_MACRO   = 17
SYM_NEXT    = 21
SYM_PLIST   = 25
FUN_PARAMS  = 5
FUN_BODY    = 9
FUN_ENV     = 13
FUN_SHAPE   = 17
STR_BYTES   = 5
VEC_ELTS    = 5
CALL_SLOT   = 1

NILV    = nil_obj + 3           ; nil (also in r13)
EOFV    = eof_obj + 3
UNB     = 1                     ; an unbound global's value (never a Lisp value)

IO_CONS = 0xFFFFFF00
IO_CYC  = 0xFFFFFF10

; ---- vectors
        .org 0x00
        JMP  boot               ; reset
        .org 0x04
        RTI                     ; IRQ (unused)
        .org 0x08
        JMP  trap_illegal
        .org 0x0C
        JMP  trap_swi
        .org 0x10
        JMP  trap_div
        .org 0x14
        JMP  trap_addr

; ---- variables (in the first 32K, so a 16-bit absolute address reaches them)
        .org 0x100
heap_limit:     .word 0         ; the end of the current half of the heap
cons_limit:     .word 0         ; heap_limit - 8
cur_start:      .word 0         ; the current half
cur_end:        .word 0
old_start:      .word 0         ; the other half
old_end:        .word 0
sym_free:       .word 0         ; next free byte in symbol space
const_free:     .word 0
code_free:      .word 0
top_sp:         .word 0         ; sp at the top level, where errors return to
stack_limit:    .word STACK_LIMIT
in_ptr:         .word 0         ; reading the prelude from memory while nonzero
in_phase:       .word 0         ; 0: the prelude, 1: the console
peek_ch:        .word -2        ; a character read ahead, or -2
gensym_n:       .word 0
print_mode:     .word 0         ; 0: display, 1: write
; statistics, for the tools
gc_count:       .word 0         ; collections
gc_copied:      .word 0         ; bytes copied by all collections
gc_alloc:       .word 0         ; bytes allocated before the current half was started
gc_save:        .word 0, 0, 0, 0    ; r9-r12 during a collection
; the root block: Lisp values the collector updates
roots:
root_a:         .word 0
root_b:         .word 0
roots_end:

; ---- jump tables ([table + r] needs a 16-bit address)
        .org 0x300
ap_tab: .word ap0, ap1, ap2, ap3, ap4, ap5, ap6     ; apply_stack, by 4 * argc
ie_tab: .word ie0, ie1, ie2, ie3, ie4, ie5, ie6     ; interp_entry, by 4 * argc
SF_TABLE = 0x340                ; sf_handlers, by a special form's index (generated)

; ---- static objects
        .org 0x400
nil_obj:        .word 1 << 8 | T_NIL << 3 | 5, not_proc
eof_obj:        .word 1 << 8 | T_EOF << 3 | 5, not_proc

; ---- start-up
        .org 0x8000
boot:   LI   sp, #STACK_TOP
        MOV  r13, #NILV
        MOV  r1, #HEAP_A
        ST   r1, [cur_start]
        MOV  r14, r1
        MOV  r1, #HEAP_A + HEAP_SIZE
        ST   r1, [cur_end]
        ST   r1, [heap_limit]
        SUB  r1, #8
        ST   r1, [cons_limit]
        MOV  r1, #HEAP_B
        ST   r1, [old_start]
        MOV  r1, #HEAP_B + HEAP_SIZE
        ST   r1, [old_end]
        MOV  r1, #sym_static_end
        ST   r1, [sym_free]
        MOV  r1, #CONST_BASE
        ST   r1, [const_free]
        MOV  r1, #CCODE_BASE
        ST   r1, [code_free]
        BSR  intern_static
        MOV  r1, #prelude_text
        ST   r1, [in_ptr]

; The top level: read a form, evaluate it, until the end of the input;
; first the prelude, then the console.
toplevel:
        ST   sp, [top_sp]
tl_loop:
        BSR  read
        CMP  r1, #EOFV
        BEQ  .eof
        MOV  r2, r13
        BSR  eval
        BRA  tl_loop
.eof:   MOV  r1, [in_phase]
        BNE  .halt
        MOV  r1, #1
        ST   r1, [in_phase]
        BRA  tl_loop
.halt:  HALT

; Abandon the top-level form after an error.
abort:  MOV  sp, [top_sp]
        MOV  r13, #NILV
        MOV  r1, [in_phase]
        BEQ  fatal_prelude
        BRA  tl_loop

fatal_prelude:
        LEA  r1, [msg_prelude]
        BRA  fatal

; fatal: r1 = a message (asciz); print it and stop.
fatal:  PUSH r1
        LEA  r1, [msg_fatal]
        BSR  puts
        POP  r1
        BSR  puts
        MOV  r1, #10
        BSR  putc
        HALT
        BRA  fatal

; ---- traps

; An address error: an access through a pointer of the wrong type. Decode
; the instruction to find which check failed, and report it as a Lisp
; error. On entry [sp] = the flags, [sp + 4] = the instruction's address.
trap_addr:
        SAVE r1-r14             ; r1 at [sp], ..., r14 at [sp + 52]
        MOV  r5, [sp + 60]      ; the instruction
        MOV  r6, half [r5]
        MOV  r7, r6
        LSR  r7, #4
        AND  r7, #15            ; the mode
        CMP  r7, #3             ; [R + d16]
        BNE  .other
        MOV  r8, half [r5 + 2]
        SXH  r8, r8             ; d16
        MOV  r7, r6
        AND  r7, #15            ; R
        BEQ  .other
        CMP  r7, #14
        BHI  .other
        LSL  r7, #2
        MOV  r1, [sp + r7 - 4]  ; R's value
        CMP  r8, #CALL_SLOT
        BEQ  err_notproc
        CMP  r8, #-1
        BEQ  err_notpair
        CMP  r8, #3
        BEQ  err_notpair
.other: LEA  r1, [msg_addr]
        BRA  fatal

trap_illegal:
        LEA  r1, [msg_illegal]
        BRA  fatal
trap_swi:
        LEA  r1, [msg_swi]
        BRA  fatal
trap_div:
        LEA  r1, [msg_div]
        BRA  fatal

; The call slot of every object that isn't a procedure: r1 = the object.
not_proc:
        BRA  err_notproc

heap_full:
        LEA  r1, [msg_heap]
        BRA  fatal

err_stack:
        LEA  r2, [msg_stack]
        BRA  error0

msg_fatal:      .asciz "fatal: "
msg_prelude:    .asciz "error in the prelude"
msg_addr:       .asciz "address error"
msg_illegal:    .asciz "illegal instruction"
msg_swi:        .asciz "SWI"
msg_div:        .asciz "divide trap"
msg_heap:       .asciz "heap full"
msg_stack:      .asciz "stack overflow"
        .align 2
