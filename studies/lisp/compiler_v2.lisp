; The compiler's draft 2 backend (RFC 0028). compiler.lisp is the compiler
; for draft 1b; for draft 2, the build puts each definition made here in
; place of compiler.lisp's of the same name, and adds the new ones after
; them (machine.py, compiler_source). So this file holds only what draft 2
; changes: the assembler, the calling convention and the frame, and the
; integer checks. compiler.md describes both.

; ======================================================================
; The assembler: symbolic instructions -> draft 2 parcels
;
; A parcel is an opcode byte, first in memory (the parcel's low byte), and
; a register byte: rd, or a mode, in its high nibble and rs, or the mode's
; register, in its low one. The operands and instructions are
; compiler.lisp's, with these besides:
;   (movs d o)    a MOV that sets N and Z
;   (clr o)       store zero
;   (tst d o) (bic d o) (mulu d o) (muls d o)    o a register or a constant
;   (ttst d s)    the tagged test: N and Z of d & s; traps unless both are
;                 integers
; and (mov d (tag s)), (add d (tag s)), (sub d (tag s)), (cmp d (tag s))
; are the tagged TMOV, TADD, TSUB and TCMP (with the tagged feature).
; (link-save), (link-restore) and (link-ret) keep the return address, and
; cc:link makes them instructions once the function is done.

(define cc:ea-ops
  '((mov . 1) (st . 2) (movs . 3) (add . 4) (sub . 5) (cmp . 6) (and . 8) (or . 9) (xor . 10)))
(define cc:unary-fns
  '((not . 0) (neg . 1) (inc . 2) (dec . 3) (swap . 6) (sxb . 7) (sxh . 8) (zxb . 9) (zxh . 10)))
(define cc:rr-fns
  '((adc . 0) (sbc . 1) (bic . 2) (tst . 3) (mulu . 4) (muls . 5) (divu . 7) (divs . 8)))
(define cc:tagged-ops '((mov . 9) (add . 11) (sub . 12) (cmp . 13)))

; a parcel: opcode byte, and the register byte's two nibbles
(define (cc:p2 op d s) (+ op (* 256 (+ (* d 16) s))))

; (mode r ext...) for an operand; pc = the address of the next instruction
; (only pcrel needs it). The modes are 1b's, and mode 14 is [r14 + 4R].
(define (cc:ea o labels pc)
  (case (car o)
    ((reg) (list 0 (cadr o)))
    ((imm) (cc:ea-imm (cadr o) (caddr o)))
    ((mem)
     (let ((r (cadr o)) (d (caddr o)))
       (cond ((= d 0) (list 2 r))
             ((and (or (= r 15) (= r 14)) (>= d 0) (<= d 60) (= (logand d 3) 0))
              (list (if (= r 15) 4 14) (quotient d 4)))
             (t (list 3 r (cc:u16 d))))))
    ((byte) (if (= (caddr o) 0) (list 8 (cadr o)) (list 9 (cadr o) (cc:u16 (caddr o)))))
    ((half) (if (= (caddr o) 0) (list 11 (cadr o)) (list 12 (cadr o) (cc:u16 (caddr o)))))
    ((pinc) (list 6 (cadr o)))
    ((pdec) (list 7 (cadr o)))
    ((bpinc) (list 10 (cadr o)))
    ((abs) (list 15 4 (cc:u16 (cadr o))))
    ((idx)
     (let ((r (list-ref o 1)) (x (list-ref o 2)) (s (list-ref o 3)) (d (list-ref o 4))
           (z (list-ref o 5)))
       (list 5 r (+ (* x 4096)
                    (* (cdr (assq s '((1 . 0) (2 . 1) (4 . 2) (8 . 3)))) 1024)
                    (* (cdr (assq z '((byte . 0) (half . 1) (word . 2)))) 256)
                    (logand d 255)))))
    ((pcrel)
     (if labels
         (list 15 10 (cc:u16 (- (cc:label-addr (cadr o) labels) pc)))
         (list 15 10 0)))
    (t (error "cc: bad operand" o))))

; a constant in the special mode only (for TST, BIC, MULU and MULS)
(define (cc:ea-spec hi lo)
  (cond ((or (and (= hi 0) (< lo 32768)) (and (= hi 65535) (>= lo 32768))) (list 15 0 lo))
        ((= hi 0) (list 15 1 lo))
        ((= lo 0) (list 15 2 hi))
        (t (list 15 3 lo hi))))

; the 7-bit constant of MOV and CMP, 16-127, or nil
(define (cc:u7 o)
  (and (eq? (car o) 'imm) (= (cadr o) 0) (>= (caddr o) 16) (<= (caddr o) 127) (caddr o)))

; LEA has no [R] (that's a MOV) and no [r14 + 4R]
(define (cc:lea-ea o labels pc)
  (let ((e (cc:ea o labels pc)))
    (if (= (car e) 14) (list 3 14 (cc:u16 (caddr o))) e)))

(define (cc:tagged? i) (and (memq (car i) '(mov add sub cmp)) (eq? (car (caddr i)) 'tag)))

; the parcels of instruction i at address pc. long: whether a branch is in
; its long form.
(define (cc:encode i pc labels long)
  (let ((op (car i)))
    (cond
     ((eq? op 'label) nil)
     ((cc:tagged? i) (list (cc:p2 (cc:lookup op cc:tagged-ops) (cadr i) (cadr (caddr i)))))
     ((and (memq op '(mov cmp)) (cc:u7 (caddr i)))
      (let ((k (cc:u7 (caddr i))))
        (list (cc:p2 (+ (if (eq? op 'mov) 112 120) (logand k 7)) (cadr i) (quotient k 8)))))
     ((assq op cc:ea-ops)
      (let ((e (cc:ea (caddr i) labels (+ pc (* 2 (cc:ea-size (caddr i)))))))
        (cons (cc:p2 (+ (* 16 (cc:lookup op cc:ea-ops)) (car e)) (cadr i) (cadr e)) (cddr e))))
     ((eq? op 'lea)
      (let ((e (cc:lea-ea (caddr i) labels (+ pc (* 2 (cc:size i nil))))))
        (if (= (car e) 2)
            (list (cc:p2 16 (cadr i) (cadr e)))
            (cons (cc:p2 (cdr (assq (car e) '((3 . 4) (4 . 5) (5 . 6) (15 . 7)))) (cadr i) (cadr e))
                  (cddr e)))))
     ((eq? op 'clr)
      (let ((e (cc:ea (cadr i) labels (+ pc (* 2 (cc:ea-size (cadr i)))))))
        (cons (cc:p2 32 (car e) (cadr e)) (cddr e))))
     ((memq op '(tst bic mulu muls))
      (let ((o (caddr i)) (f (cc:lookup op cc:rr-fns)))
        (if (eq? (car o) 'reg)
            (list (cc:p2 (+ 224 f) (cadr i) (cadr o)))
            (let ((e (cc:ea-spec (cadr o) (caddr o))))
              (cons (cc:p2 (+ 232 f) (cadr i) (cadr e)) (cddr e))))))
     ((eq? op 'ttst) (list (cc:p2 10 (cadr i) (caddr i))))
     ((or (eq? op 'jmpea) (eq? op 'callea))
      (let ((e (cc:ea (cadr i) labels (+ pc (* 2 (cc:ea-size (cadr i)))))))
        (cons (cc:p2 (if (eq? op 'callea) 241 240) (car e) (cadr e)) (cddr e))))
     ((eq? op 'unary) (list (cc:p2 (+ 208 (cc:lookup (cadr i) cc:unary-fns)) (caddr i) (cadddr i))))
     ((eq? op 'shift)
      (let ((n (cadddr i)) (f (cc:lookup (cadr i) cc:shift-fns)))
        (list (cc:p2 (+ 192 (* 4 f) (logand n 1)) (caddr i) (quotient n 2)))))
     ((eq? op 'shiftr)
      (list (cc:p2 (+ 194 (* 4 (cc:lookup (cadr i) cc:shift-fns))) (caddr i) (cadddr i))))
     ((eq? op 'rr) (list (cc:p2 (+ 224 (cc:lookup (cadr i) cc:rr-fns)) (caddr i) (cadddr i))))
     ((or (eq? op 'b) (eq? op 'bsr))
      (let ((c (if (eq? op 'bsr) 15 (cc:lookup (cadr i) cc:conds)))
            (target (if labels (cc:label-addr (if (eq? op 'bsr) (cadr i) (caddr i)) labels) pc)))
        (if long
            (list (cc:p2 242 c 0) (cc:u16 (quotient (- target (+ pc 4)) 2)))
            (list (+ 176 c (* 256 (logand (quotient (- target (+ pc 2)) 2) 255)))))))
     ((eq? op 'rt)
      (let ((c (cc:lookup (cadr i) cc:conds)) (target (caddr i)))
        (if long
            (list (cc:p2 243 c 0) (cc:u16 target) (cc:u16 (ash target -16)))
            (list (cc:p2 242 c 0) (cc:u16 (quotient (- target (+ pc 4)) 2))))))
     ((eq? op 'save) (list (cc:p2 244 (cadr i) (caddr i))))
     ((eq? op 'restore) (list (cc:p2 245 (cadr i) (caddr i))))
     ((eq? op 'ret) (list (cc:p2 240 0 7)))
     ((eq? op 'jmpr) (list (cc:p2 240 0 (cadr i))))
     ((eq? op 'nop) (list 16))
     (t (error "cc: bad instruction" i)))))

(define (cc:size i long)
  (let ((op (car i)))
    (cond ((eq? op 'label) 0)
          ((cc:tagged? i) 1)
          ((and (memq op '(mov cmp)) (cc:u7 (caddr i))) 1)
          ((assq op cc:ea-ops) (cc:ea-size (caddr i)))
          ((eq? op 'lea) (- (length (cc:lea-ea (caddr i) nil 0)) 1))
          ((eq? op 'clr) (cc:ea-size (cadr i)))
          ((memq op '(tst bic mulu muls))
           (if (eq? (car (caddr i)) 'reg)
               1
               (- (length (cc:ea-spec (cadr (caddr i)) (caddr (caddr i)))) 1)))
          ((or (eq? op 'jmpea) (eq? op 'callea)) (cc:ea-size (cadr i)))
          ((or (eq? op 'b) (eq? op 'bsr)) (if long 2 1))
          ((eq? op 'rt) (if long 3 2))
          (t 1))))

; ======================================================================
; Code generation on draft 2
;
; Registers: r1 = the value of an expression; arguments in r3, r4, r5, r6,
; r8, r0; r2 the argument count at calls; r7 the link register; r9 raw
; scratch; r13 = nil, r14 = the heap pointer, r15 = sp.
; A function that calls anything pushes r7 on entry, below its frame, and
; returns with JMP [sp]+; a leaf keeps it in r7 and returns with RET.

(define cc:arg-regs '(3 4 5 6 8 0))

(define (cc:ret tail)
  (when tail
    (cc:emit-frame-pop)
    (cc:e 'return '(link-ret))))

(define (cc:g-call f args tail)
  (let* ((n (length args))
         (known (and (eq? (car f) 'lref) (cc:var-known (cadr f))))
         (complex-f (not (or (eq? (car f) 'gref) (cc:simple? f))))
         (complex-args (not (null? (cc:filter (lambda (a) (not (cc:simple? a))) args)))))
    (when (and known (not (cc:arity-ok? known n))) (set! known nil))
    ; the operator first (the interpreter evaluates it first)
    (cond (complex-f (cc:g f nil) (cc:push 1))
          ((and (eq? (car f) 'gref) complex-args) (cc:load-global (cadr f))))
    (if (> n 6)
        (cc:many-args args)
        (cc:args-into args (cc:take cc:arg-regs n)))
    (cond (complex-f (cc:pop 1))
          ((eq? (car f) 'gref)
           (if complex-args
               (cc:e 'global (list 'mov 1 (list 'abs (+ (%address (cadr f)) 5))))
               (cc:load-global (cadr f))))
          ((eq? (car f) 'const) (cc:load-const (cadr f) 1))
          (t (cc:load-var (cadr f) 1)))
    (cond (known (cc:known-call known n tail))
          (t
           (cc:e 'call (list 'mov 2 (cc:imm n)))
           (if tail
               (begin (cc:emit-frame-pop)
                      (cc:e 'call '(link-restore))
                      (cc:e 'call '(jmpea (mem 1 1))))
               (cc:e 'call '(callea (mem 1 1))))))))

; a call to a letrec-bound lambda: straight to its body, past the check of
; the argument count; a tail call to itself is a jump past its PUSH r7
(define (cc:known-call lam n tail)
  (if (cc:lam-rest lam) (cc:e 'call (list 'mov 2 (cc:imm n))))
  (cond ((not tail) (cc:e 'call (list 'bsr (cc:lam-start lam))))
        ((eq? lam cc:*lam*)
         (cc:emit-frame-pop)
         (cc:e 'call (list 'b 'ra cc:*self-start*)))
        (t
         (cc:emit-frame-pop)
         (cc:e 'call '(link-restore))
         (cc:e 'call (list 'b 'ra (cc:lam-start lam))))))

; more than 6 arguments: 1-5 in r3-r6 and r8, a list of the rest in r0
(define (cc:many-args args)
  (cc:for-each (lambda (a) (cc:g a nil) (cc:push 1)) args)
  (cc:e 'call '(mov 4 (reg 13)))
  (let loop ((k (- (length args) 5)))
    (when (> k 0)
      (cc:pop 3)
      (cc:e 'call (list 'rt 'call (cc:rt 'cons)))
      (cc:e 'call '(mov 4 (reg 1)))
      (loop (- k 1))))
  (cc:e 'call '(mov 0 (reg 4)))
  (cc:for-each (lambda (r) (cc:pop r)) '(8 6 5 4 3)))

; the collector's stub keeps r7 on the stack, so consing alone doesn't
; make a function keep its return address there
(define (cc:gen-cons)                  ; r3 = car, r4 = cdr -> r1
  (let ((back (cc:label)))
    (cc:e 'alloc (list 'cmp 14 (list 'abs (cc:rt 'cons-limit))))
    (cc:e 'alloc (list 'b 'hi (cc:stub (list 'gc back)
                                   (list '(st 7 (pdec 15)) (list 'rt 'call (cc:rt 'gc))
                                         '(mov 7 (pinc 15)) (list 'b 'ra back)))))
    (cc:emit-label back)
    (cc:e 'alloc '(st 3 (pinc 14)))
    (cc:e 'alloc '(st 4 (pinc 14)))
    (cc:e 'alloc '(lea 1 (mem 14 -7)))))

(define (cc:check-num r)               ; r is a fixnum, else "not a number"
  (if (cc:option? 'tagged)
      (cc:e 'type (list 'ttst r r))
      (cc:check-num-sw r)))

(define (cc:check-num-sw r)
  (cc:e 'type (list 'tst r '(imm 0 1)))
  (cc:e 'type (list 'b 'ne (if (= r 1) (cc:err-stub 'notnum) (cc:err3-stub 'notnum)))))

; a primitive as a test: jump to false if it's nil
(define (cc:test-prim name args false)
  (case name
    ((not null?)
     (if (cc:testable? (car args))
         ; (not test): the test, with its outcomes swapped
         (let ((true (cc:label)))
           (cc:test (car args) true)
           (cc:e 'test (list 'b 'ra false))
           (cc:emit-label true))
         (begin
           (cc:g (car args) nil)
           (cc:e 'test '(cmp 1 (reg 13)))
           (cc:e 'test (list 'b 'ne false)))))
    ((eq?)
     (if (cc:simple? (cadr args))
         (begin (cc:g (car args) nil)
                (if (and (eq? (car (cadr args)) 'const) (null? (cadr (cadr args))))
                    (cc:e 'test '(cmp 1 (reg 13)))
                    (begin (cc:args-into (cdr args) '(3)) (cc:e 'test '(cmp 1 (reg 3))))))
         (begin (cc:args-into args '(1 3)) (cc:e 'test '(cmp 1 (reg 3)))))
     (cc:e 'test (list 'b 'ne false)))
    ((pair? atom?)
     (cc:g (car args) nil)
     (cc:e 'pred '(mov 9 (reg 1)))
     (cc:e 'pred '(and 9 (imm 0 3)))
     (cc:e 'pred '(cmp 9 (imm 0 1)))
     (cc:e 'test (list 'b (if (eq? name 'pair?) 'ne 'eq) false)))
    ((number? integer?)
     (cc:g (car args) nil)
     (cc:e 'pred '(tst 1 (imm 0 1)))
     (cc:e 'test (list 'b 'ne false)))
    ((symbol?)
     (cc:g (car args) nil)
     (cc:e 'pred '(mov 9 (reg 1)))
     (cc:e 'pred '(and 9 (imm 0 3)))
     (cc:e 'pred '(cmp 9 (imm 0 3)))
     (cc:e 'test (list 'b 'ne false))
     (cc:e 'test '(cmp 1 (reg 13)))
     (cc:e 'test (list 'b 'eq false))
     (cc:e 'pred '(mov 9 (byte 1 -3)))
     (cc:e 'pred '(cmp 9 (imm 0 5)))       ; B_SYM
     (cc:e 'test (list 'b 'ne false)))
    ((zero?)
     (cc:g (car args) nil)
     (if (cc:option? 'tagged)
         (cc:e 'arith '(ttst 1 1))         ; the check, and Z
         (begin (cc:check-num 1) (cc:e 'test '(cmp 1 (imm 0 0)))))
     (cc:e 'test (list 'b 'ne false)))
    ((= < > <= >=)
     (let ((o (cc:num-args args)))
       (cc:e 'arith (list 'cmp 1 o))
       (cc:e 'test (list 'b (cc:lookup (cc:lookup name '((= . eq) (< . lt) (> . gt) (<= . le) (>= . ge)))
                                    cc:inverse)
                      false))))
    (t (cc:g-prim name args)
       (cc:e 'test '(cmp 1 (reg 13)))
       (cc:e 'test (list 'b 'eq false)))))

; ---- functions

(define cc:*self-start* nil)           ; where the function's tail calls to itself go

(define (cc:g-function lam)
  (set! cc:*lam* lam)
  (set! cc:*stubs* nil)
  (set! cc:*self-start* (cc:label))
  (let* ((req (cc:lam-req lam))
         (rest (cc:lam-rest lam))
         (params (if rest (append req (list rest)) req))
         (np (length params))
         (nreq (length req))
         (mark cc:*code*))             ; the instructions before this function's
    (cc:emit-label (cc:lam-entry lam))
    (cc:e 'entry (list 'cmp 2 (cc:imm nreq)))
    (cc:e 'entry (list 'b (if rest 'lo 'ne) (cc:err-stub 'argc)))
    (cc:emit-label (cc:lam-start lam))
    (cc:e 'entry '(link-save))
    (cc:emit-label cc:*self-start*)
    (cc:e 'entry (list 'cmp 15 (list 'abs (cc:rt 'stack-limit))))
    (cc:e 'entry (list 'b 'lo (cc:err-stub 'stack)))
    (when rest
      (cc:e 'entry (list 'mov 9 (cc:imm nreq)))
      (cc:e 'entry (list 'rt 'call (cc:rt 'rest)))
      (cc:e 'entry (list 'mov (list-ref cc:arg-regs nreq) '(reg 12))))
    (set! cc:*depth* 0)
    ; the arguments, the first at [sp]: 5 and 6 pushed, then SAVE r3-rN
    (when (> np 5) (cc:e 'entry '(st 0 (pdec 15))))
    (when (> np 4) (cc:e 'entry '(st 8 (pdec 15))))
    (when (> np 0) (cc:e 'entry (list 'save 3 (+ 2 (if (> np 4) 4 np)))))
    (set! cc:*depth* np)
    (let loop ((l params) (i (- np 1)))
      (when (pair? l) (vector-set! (car l) 4 i) (loop (cdr l) (- i 1))))
    (if (pair? (cc:lam-free lam))
        (begin (set! cc:*clo* cc:*depth*) (cc:push 1))
        (set! cc:*clo* nil))
    ; parameters that need boxes get them now
    (cc:for-each (lambda (v)
                   (when (cc:boxed? v)
                     (cc:load-var-raw v 1)
                     (cc:e 'alloc '(mov 3 (reg 1)))
                     (cc:e 'alloc '(mov 4 (reg 13)))
                     (cc:gen-cons)
                     (cc:e 'alloc (list 'st 1 (list 'mem 15 (cc:off (cc:var-index v)))))))
                 params)
    (cc:g (cc:lam-body lam) t)
    (cc:for-each (lambda (s) (cc:emit-label (cadr s)) (cc:for-each (lambda (i) (cc:e 'stub i)) (caddr s)))
                 (reverse cc:*stubs*))
    (cc:link mark)))

; the function just compiled, cc:*code* back to mark: if it calls anything
; (but a call right after PUSH r7, which keeps r7 itself), its return
; address goes on the stack on entry and comes back from there; a leaf
; keeps it in r7
(define (cc:link mark)
  (let ((leaf (cc:leaf? cc:*code* mark)))
    (let loop ((l cc:*code*) (c cc:*cats*) (out nil) (cout nil))
      (if (eq? l mark)
          (begin (set! cc:*code* (cc:revappend out l))
                 (set! cc:*cats* (cc:revappend cout c)))
          (let* ((i (car l))
                 (new (cond ((eq? (car i) 'link-save) (if leaf nil '(st 7 (pdec 15))))
                            ((eq? (car i) 'link-restore) (if leaf nil '(mov 7 (pinc 15))))
                            ((eq? (car i) 'link-ret) (if leaf '(ret) '(jmpea (pinc 15))))
                            (t i))))
            (if new
                (loop (cdr l) (cdr c) (cons new out) (cons (car c) cout))
                (loop (cdr l) (cdr c) out cout)))))))

; no call between l and mark (instructions last first)
(define (cc:leaf? l mark)
  (cond ((eq? l mark) t)
        ((and (or (memq (car (car l)) '(callea bsr))
                  (and (eq? (car (car l)) 'rt) (eq? (cadr (car l)) 'call)))
              (not (and (pair? (cdr l)) (equal? (cadr l) '(st 7 (pdec 15))))))
         nil)
        (t (cc:leaf? (cdr l) mark))))

(define (cc:revappend a b) (if (null? a) b (cc:revappend (cdr a) (cons (car a) b))))
