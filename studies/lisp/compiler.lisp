; A compiler from the language to draft 1b machine code, written in the
; language and running on the machine. Loading this file installs it as the
; top level: every later form is compiled, then run. compiler.md describes
; it; the calling convention and data layout are implementation.md's.
;
; All its global names start with cc: so programs can't clash with them.
;
; Passes, for one top-level form:
;   cc:x       the form -> an AST, with macros expanded and variables resolved
;   cc:free    which variables each lambda captures
;   cc:gen     the AST -> 1b instructions (symbolic), one block per form
;   cc:asm     instructions -> 16-bit parcels, branches sized to fit
;   cc:install the parcels into code space, the closures patched
;
; Anything it can't compile (a lambda with too many parameters, a quoted
; constant that can't be copied out of the heap, ...) makes it hand the
; form to the interpreter instead.

; ======================================================================
; Utilities

; cc:*options* (defined before this file is loaded) lists the features:
;   tagged   v1bx's tagged register mode does the integer checks
(define (cc:option? x) (memq x cc:*options*))

(define cc:*fail* nil)
(define (cc:fail why)
  (if (not cc:*fail*) (set! cc:*fail* why))
  (list 'const nil))

(define (cc:index x l)
  (let loop ((l l) (i 0))
    (cond ((null? l) nil)
          ((eq? (car l) x) i)
          (t (loop (cdr l) (+ i 1))))))

(define (cc:proper? l)
  (cond ((null? l) t)
        ((pair? l) (cc:proper? (cdr l)))
        (t nil)))

(define (cc:map f l)
  (if (null? l) nil (let ((x (f (car l)))) (cons x (cc:map f (cdr l))))))

(define (cc:for-each f l)
  (if (null? l) nil (begin (f (car l)) (cc:for-each f (cdr l)))))

(define (cc:each2 f a b)
  (when (pair? a) (f (car a) (car b)) (cc:each2 f (cdr a) (cdr b))))

(define (cc:adjoin x l) (if (memq x l) l (cons x l)))

(define (cc:last l) (if (null? (cdr l)) (car l) (cc:last (cdr l))))

; ======================================================================
; The assembler: symbolic instructions -> parcels
;
; Registers are 0-15. Operands of the EA instructions:
;   (reg r)  (imm hi lo)  (mem r d)  (byte r d)  (half r d)  (pinc r)
;   (pdec r)  (bpinc r)  (abs a)  (idx r x scale d size)  (pcrel label)
; Instructions:
;   (mov d o) (st d o) (lea d o) (add d o) (sub d o) (cmp d o) (and d o)
;   (or d o) (xor d o)  (jmpea o) (callea o)  (unary f d s)  (shift f d n)
;   (shiftr f d s)  (rr f d s)  (b cc label) (bsr label)  (rt cc addr)
;   (save a b) (restore a b) (ret) (jmpr r) (nop)  (label l)
; (b cc l) becomes a 2-parcel Jcc when the target is out of range; (rt cc
; addr) jumps (cc = ra), calls (cc = call) or branches to an absolute
; address, PC-relative if it can.

(define cc:ea-ops
  '((mov . 1) (st . 2) (lea . 3) (add . 4) (sub . 5) (cmp . 6) (and . 7) (or . 8) (xor . 9)))
(define cc:conds
  '((eq . 0) (ne . 1) (hs . 2) (lo . 3) (mi . 4) (pl . 5) (vs . 6) (vc . 7)
    (hi . 8) (ls . 9) (ge . 10) (lt . 11) (gt . 12) (le . 13) (ra . 14) (call . 15)))
(define cc:inverse
  '((eq . ne) (ne . eq) (hs . lo) (lo . hs) (mi . pl) (pl . mi) (vs . vc) (vc . vs)
    (hi . ls) (ls . hi) (ge . lt) (lt . ge) (gt . le) (le . gt)))
(define cc:unary-fns
  '((not . 0) (neg . 1) (inc . 2) (dec . 3) (swap . 6) (sxb . 7) (zxb . 8) (sxh . 9) (zxh . 10)))
(define cc:shift-fns '((lsl . 0) (lsr . 1) (asr . 2) (ror . 3)))
(define cc:rr-fns
  '((adc . 0) (sbc . 1) (bic . 2) (tst . 3) (mulu . 4) (muls . 5) (divu . 6) (divs . 7)))

(define (cc:p4 a b c d) (+ (* a 4096) (* b 256) (* c 16) d))
(define (cc:u16 x) (logand x 65535))
(define (cc:lookup k al) (cdr (assq k al)))

(define (cc:s16? d) (and (>= d -32768) (<= d 32767)))

; an immediate operand from an integer (a raw 32-bit word that fits 31 bits)
(define (cc:imm k) (list 'imm (cc:u16 (ash k -16)) (cc:u16 k)))
; the raw word of the fixnum n, which may need all 32 bits
(define (cc:fix n)
  (list 'imm (cc:u16 (ash n -15)) (cc:u16 (* 2 (logand n 32767)))))

; (mode r ext...) for an operand; pc = the address of the next instruction
; (only pcrel needs it)
(define (cc:ea o labels pc)
  (case (car o)
    ((reg) (list 0 (cadr o)))
    ((imm) (cc:ea-imm (cadr o) (caddr o)))
    ((mem)
     (let ((r (cadr o)) (d (caddr o)))
       (cond ((= d 0) (list 2 r))
             ((and (= r 15) (>= d 0) (<= d 60) (= (logand d 3) 0)) (list 4 (quotient d 4)))
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
    ((tag) (list 14 (cadr o)))           ; v1bx: a tagged register (isa.md)
    ((pcrel)
     (if labels
         (list 15 10 (cc:u16 (- (cc:label-addr (cadr o) labels) pc)))
         (list 15 10 0)))
    (t (error "cc: bad operand" o))))

(define (cc:ea-imm hi lo)
  (cond ((and (= hi 0) (<= lo 15)) (list 1 lo))
        ((and (= hi 65535) (>= lo 65520)) (list 13 (- 65535 lo)))
        ((or (and (= hi 0) (< lo 32768)) (and (= hi 65535) (>= lo 32768))) (list 15 0 lo))
        ((= hi 0) (list 15 1 lo))
        ((= lo 0) (list 15 2 hi))
        (t (list 15 3 lo hi))))

(define (cc:label-addr l labels)
  (let ((b (assq l labels)))
    (if b (cdr b) (error "cc: no label" l))))

; the parcels of instruction i at address pc. long: whether a branch is in
; its long form.
(define (cc:encode i pc labels long)
  (let ((op (car i)))
    (cond
     ((assq op cc:ea-ops)
      (let ((e (cc:ea (caddr i) labels (+ pc (* 2 (cc:ea-size (caddr i)))))))
        (cons (cc:p4 (cc:lookup op cc:ea-ops) (cadr i) (car e) (cadr e)) (cddr e))))
     ((eq? op 'label) nil)
     ((or (eq? op 'jmpea) (eq? op 'callea))
      (let ((e (cc:ea (cadr i) labels (+ pc (* 2 (cc:ea-size (cadr i)))))))
        (cons (cc:p4 11 (if (eq? op 'callea) 1 0) (car e) (cadr e)) (cddr e))))
     ((eq? op 'unary) (list (cc:p4 12 (caddr i) (cadddr i) (cc:lookup (cadr i) cc:unary-fns))))
     ((eq? op 'shift)
      (let ((n (cadddr i)) (f (cc:lookup (cadr i) cc:shift-fns)))
        (list (if (< n 16) (cc:p4 13 (caddr i) n f) (cc:p4 13 (caddr i) (- n 16) (+ f 4))))))
     ((eq? op 'shiftr)
      (list (cc:p4 13 (caddr i) (cadddr i) (+ (cc:lookup (cadr i) cc:shift-fns) 8))))
     ((eq? op 'rr) (list (cc:p4 15 (caddr i) (cadddr i) (cc:lookup (cadr i) cc:rr-fns))))
     ((or (eq? op 'b) (eq? op 'bsr))
      (let ((c (if (eq? op 'bsr) 15 (cc:lookup (cadr i) cc:conds)))
            (target (if labels (cc:label-addr (if (eq? op 'bsr) (cadr i) (caddr i)) labels) pc)))
        (if long
            (list (cc:p4 10 c 0 0) (cc:u16 (quotient (- target (+ pc 4)) 2)))
            (list (+ (cc:p4 14 c 0 0) (logand (quotient (- target (+ pc 2)) 2) 255))))))
     ((eq? op 'rt)
      (let ((c (cc:lookup (cadr i) cc:conds)) (target (caddr i)))
        (if long
            (list (cc:p4 10 c 1 0) (cc:u16 target) (cc:u16 (ash target -16)))
            (list (cc:p4 10 c 0 0) (cc:u16 (quotient (- target (+ pc 4)) 2))))))
     ((eq? op 'save) (list (cc:p4 0 (cadr i) (caddr i) 5)))
     ((eq? op 'restore) (list (cc:p4 0 (cadr i) (caddr i) 6)))
     ((eq? op 'ret) (list 4))
     ((eq? op 'jmpr) (list (cc:p4 0 0 (cadr i) 2)))
     ((eq? op 'nop) (list 1))
     (t (error "cc: bad instruction" i)))))

; parcels an instruction with this operand takes (without encoding it)
(define (cc:ea-size o)
  (case (car o)
    ((reg pinc pdec bpinc tag) 1)
    ((imm) (- (length (cc:ea-imm (cadr o) (caddr o))) 1))
    ((mem) (- (length (cc:ea o nil 0)) 1))
    ((byte half) (if (= (caddr o) 0) 1 2))
    ((abs idx pcrel) 2)
    (t (error "cc: bad operand" o))))

(define (cc:size i long)
  (let ((op (car i)))
    (cond ((assq op cc:ea-ops) (cc:ea-size (caddr i)))
          ((eq? op 'label) 0)
          ((or (eq? op 'jmpea) (eq? op 'callea)) (cc:ea-size (cadr i)))
          ((or (eq? op 'b) (eq? op 'bsr)) (if long 2 1))
          ((eq? op 'rt) (if long 3 2))
          (t 1))))

; assemble a list of instructions at base -> (parcels labels cats): cats
; holds each parcel's category, given each instruction's in cats
(define (cc:asm insns base . cats)
  (let* ((n (length insns))
         (v (make-vector n nil))
         (long (make-vector n nil)))
    (let fill ((l insns) (k 0))
      (when (pair? l) (vector-set! v k (car l)) (fill (cdr l) (+ k 1))))
    (let pass ()
      ; lay out, then lengthen anything out of range, until nothing changes
      (let ((labels (cc:layout v long n base)) (changed nil))
        (do ((k 0 (+ k 1)) (pc base (+ pc (* 2 (cc:size (vector-ref v k) (vector-ref long k))))))
            ((= k n))
          (let ((i (vector-ref v k)))
            (when (and (not (vector-ref long k)) (memq (car i) '(b bsr rt)))
              (let* ((target (case (car i)
                               ((b) (cc:label-addr (caddr i) labels))
                               ((bsr) (cc:label-addr (cadr i) labels))
                               (t (caddr i))))
                     (off (quotient (- target (+ pc 2)) 2)))
                (when (if (eq? (car i) 'rt)
                          (not (cc:s16? (quotient (- target (+ pc 4)) 2)))
                          (or (< off -128) (> off 127)))
                  (vector-set! long k t)
                  (set! changed t))))))
        (if changed
            (pass)
            (let emit ((k 0) (pc base) (out nil) (cs (if (pair? cats) (car cats) nil)) (cout nil))
              (if (= k n)
                  (list (reverse out) labels (reverse cout))
                  (let ((ps (cc:encode (vector-ref v k) pc labels (vector-ref long k)))
                        (c (if (pair? cs) (car cs) 'other)))
                    (emit (+ k 1) (+ pc (* 2 (length ps))) (append (reverse ps) out)
                          (if (pair? cs) (cdr cs) nil)
                          (let more ((p ps) (cout cout))
                            (if (null? p) cout (more (cdr p) (cons c cout)))))))))))))

(define (cc:layout v long n base)
  (let loop ((k 0) (pc base) (labels nil))
    (if (= k n)
        labels
        (let ((i (vector-ref v k)))
          (loop (+ k 1)
                (+ pc (* 2 (cc:size i (vector-ref long k))))
                (if (eq? (car i) 'label) (cons (cons (cadr i) pc) labels) labels))))))

; ======================================================================
; The front end: a form -> an AST
;
; AST nodes:
;   (const x) (lref var) (lset var e) (gref sym) (gset sym e)
;   (if c a b) (and e...) (or e...) (seq e...)
;   (let vars inits body) (letrec vars inits body)
;   (lambda lam) (call f args) (prim name args) (syntax-error form)
;
; A variable is a vector: name, assigned?, captured?, owner (its lambda),
; frame index, known lambda (letrec-bound and never assigned).
; A lambda is a vector: required vars, rest var or nil, body, free vars,
; entry label, body label, name, static closure.

(define (cc:make-var name owner)
  (let ((v (make-vector 6 nil))) (vector-set! v 0 name) (vector-set! v 3 owner) v))
(define (cc:var-assigned? v) (vector-ref v 1))
(define (cc:var-captured? v) (vector-ref v 2))
(define (cc:var-owner v) (vector-ref v 3))
(define (cc:var-index v) (vector-ref v 4))
(define (cc:var-known v) (vector-ref v 5))
(define (cc:boxed? v) (and (cc:var-assigned? v) (cc:var-captured? v)))

(define (cc:lam-req l) (vector-ref l 0))
(define (cc:lam-rest l) (vector-ref l 1))
(define (cc:lam-body l) (vector-ref l 2))
(define (cc:lam-free l) (vector-ref l 3))
(define (cc:lam-entry l) (vector-ref l 4))
(define (cc:lam-start l) (vector-ref l 5))
(define (cc:lam-static l) (vector-ref l 7))

(define cc:*label* 0)
(define (cc:label) (set! cc:*label* (+ cc:*label* 1)) cc:*label*)

; the lambda whose body is being built (variables made now belong to it)
(define cc:*owner* nil)

(define (cc:x x env)
  (cond ((symbol? x)
         (let ((b (assq x env)))
           (if b (list 'lref (cdr b)) (cc:gref x))))
        ((pair? x) (cc:x-pair x env))
        (t (list 'const x))))

(define (cc:gref s)
  (cond ((not (%address s)) (cc:fail "a global in the heap"))
        ((and (eq? s 't) (eq? (eval 't) 't)) (list 'const 't))
        (t (list 'gref s))))

(define (cc:x-list l env) (cc:map (lambda (x) (cc:x x env)) l))

(define (cc:x-body body env)
  (cond ((null? body) (list 'const nil))
        ((null? (cdr body)) (cc:x (car body) env))
        (t (cons 'seq (cc:x-list body env)))))

(define (cc:x-pair x env)
  (let ((op (car x)))
    (cond ((and (symbol? op) (%special? op)) (cc:x-special op x env))
          ((and (symbol? op) (%macro op))
           (if (cc:proper? (cdr x))
               (cc:x (apply (%macro op) (cdr x)) env)
               (list 'syntax-error x)))
          ((not (cc:proper? (cdr x))) (list 'syntax-error x))
          (t (cc:x-call (cc:x op env) (cc:x-list (cdr x) env))))))

(define (cc:x-call f args)
  (if (and (eq? (car f) 'gref) (cc:inline? (cadr f) (length args)))
      (list 'prim (cadr f) args)
      (list 'call f args)))

; ---- inlined primitives: (name arity), when the global still holds the
; primitive it held when the compiler was loaded

(define cc:*prims*
  (cc:map (lambda (e) (list (car e) (cadr e) (eval (car e))))
          '((car 1) (cdr 1) (cons 2) (set-car! 2) (set-cdr! 2)
            (caar 1) (cadr 1) (cdar 1) (cddr 1) (caddr 1) (cdddr 1) (cadddr 1)
            (eq? 2) (not 1) (null? 1) (pair? 1) (atom? 1) (number? 1) (integer? 1) (symbol? 1)
            (+ 2) (- 2) (- 1) (* 2) (= 2) (< 2) (> 2) (<= 2) (>= 2) (zero? 1)
            (vector-ref 2) (vector-set! 3) (vector-length 1))))

(define (cc:inline? s n)
  (let loop ((l cc:*prims*))
    (cond ((null? l) nil)
          ((and (eq? (car (car l)) s) (= (cadr (car l)) n))
           (eq? (eval s) (caddr (car l))))
          (t (loop (cdr l))))))

; ---- special forms, checked as the interpreter checks them

(define (cc:params-ok? p)
  (cond ((null? p) t)
        ((symbol? p) t)
        ((and (pair? p) (symbol? (car p))) (cc:params-ok? (cdr p)))
        (t nil)))

(define (cc:binding-ok? b)
  (and (pair? b) (symbol? (car b)) (pair? (cdr b)) (null? (cddr b))))

(define (cc:bindings-ok? bs)
  (cond ((null? bs) t)
        ((pair? bs) (and (cc:binding-ok? (car bs)) (cc:bindings-ok? (cdr bs))))
        (t nil)))

(define (cc:clauses-ok? cs)
  (cond ((null? cs) t)
        ((pair? cs) (and (pair? (car cs)) (cc:proper? (car cs)) (cc:clauses-ok? (cdr cs))))
        (t nil)))

(define (cc:x-special op x env)
  (let ((r (cdr x)) (bad (list 'syntax-error x)))
    (case op
      ((quote) (if (and (pair? r) (null? (cdr r))) (list 'const (car r)) bad))
      ((if)
       (if (and (pair? r) (pair? (cdr r))
                (or (null? (cddr r)) (and (pair? (cddr r)) (null? (cdddr r)))))
           (list 'if (cc:x (car r) env) (cc:x (cadr r) env)
                 (if (null? (cddr r)) (list 'const nil) (cc:x (caddr r) env)))
           bad))
      ((define)
       (cond ((not (pair? r)) bad)
             ((symbol? (car r))
              (if (and (pair? (cdr r)) (null? (cddr r)))
                  (cc:x-define (car r) (cc:x (cadr r) env))
                  bad))
             ((and (pair? (car r)) (symbol? (car (car r))))
              (if (and (cc:params-ok? (cdr (car r))) (cc:proper? (cdr r)))
                  (cc:x-define (car (car r))
                               (cc:x-lambda (cdr (car r)) (cdr r) env (car (car r))))
                  bad))
             (t bad)))
      ((set!)
       (if (and (pair? r) (symbol? (car r)) (pair? (cdr r)) (null? (cddr r)))
           (let ((b (assq (car r) env)) (e (cc:x (cadr r) env)))
             (if b
                 (begin (vector-set! (cdr b) 1 t) (list 'lset (cdr b) e))
                 (if (%address (car r)) (list 'gset (car r) e) (cc:fail "a global in the heap"))))
           bad))
      ((lambda)
       (if (and (pair? r) (cc:params-ok? (car r)) (cc:proper? (cdr r)))
           (cc:x-lambda (car r) (cdr r) env nil)
           bad))
      ((begin) (if (cc:proper? r) (cc:x-body r env) bad))
      ((let)
       (cond ((not (pair? r)) bad)
             ((symbol? (car r))
              (if (and (pair? (cdr r)) (cc:bindings-ok? (cadr r)) (cc:proper? (cddr r)))
                  (cc:x-named-let (car r) (cadr r) (cddr r) env)
                  bad))
             ((and (cc:bindings-ok? (car r)) (cc:proper? (cdr r)))
              (let ((vars (cc:map (lambda (b) (cc:make-var (car b) cc:*owner*)) (car r))))
                (list 'let vars
                      (cc:map (lambda (b) (cc:x (cadr b) env)) (car r))
                      (cc:x-body (cdr r) (cc:bind (car r) vars env)))))
             (t bad)))
      ((let*)
       (if (and (pair? r) (cc:bindings-ok? (car r)) (cc:proper? (cdr r)))
           (let loop ((bs (car r)) (env env))
             (if (null? bs)
                 (cc:x-body (cdr r) env)
                 (let ((v (cc:make-var (car (car bs)) cc:*owner*)))
                   (list 'let (list v) (list (cc:x (cadr (car bs)) env))
                         (loop (cdr bs) (cons (cons (car (car bs)) v) env))))))
           bad))
      ((letrec)
       (if (and (pair? r) (cc:bindings-ok? (car r)) (cc:proper? (cdr r)))
           (let* ((vars (cc:map (lambda (b) (cc:make-var (car b) cc:*owner*)) (car r)))
                  (env2 (cc:bind (car r) vars env)))
             (list 'letrec vars
                   (cc:map (lambda (b) (cc:x-named (cadr b) env2 (car b))) (car r))
                   (cc:x-body (cdr r) env2)))
           bad))
      ((cond) (if (cc:clauses-ok? r) (cc:x-cond r env) bad))
      ((and)
       (cond ((not (cc:proper? r)) bad)
             ((null? r) (list 'const 't))
             ((null? (cdr r)) (cc:x (car r) env))
             (t (cons 'and (cc:x-list r env)))))
      ((or)
       (cond ((not (cc:proper? r)) bad)
             ((null? r) (list 'const nil))
             ((null? (cdr r)) (cc:x (car r) env))
             (t (cons 'or (cc:x-list r env)))))
      ((defmacro)
       (if (and (pair? r) (symbol? (car r)) (pair? (cdr r))
                (cc:params-ok? (cadr r)) (cc:proper? (cddr r)))
           (list 'seq
                 (cc:x-call (cc:gref '%set-macro!)
                            (list (list 'const (car r))
                                  (cc:x-lambda (cadr r) (cddr r) nil (car r))))
                 (list 'const (car r)))
           bad))
      (t (cc:fail "an unknown special form")))))

(define (cc:bind names vars env)
  (if (null? names)
      env
      (cons (cons (if (pair? (car names)) (car (car names)) (car names)) (car vars))
            (cc:bind (cdr names) (cdr vars) env))))

(define (cc:x-define s e)
  (if (%address s)
      (list 'seq (list 'gset s e) (list 'const s))
      (cc:fail "a global in the heap")))

; a lambda expression, or another expression, named (for letrec)
(define (cc:x-named x env name)
  (if (and (pair? x) (eq? (car x) 'lambda) (%special? 'lambda)
           (pair? (cdr x)) (cc:params-ok? (cadr x)) (cc:proper? (cddr x)))
      (cc:x-lambda (cadr x) (cddr x) env name)
      (cc:x x env)))

(define (cc:x-lambda params body env name)
  (let ((lam (make-vector 8 nil)) (outer cc:*owner*))
    (set! cc:*owner* lam)
    (let loop ((p params) (req nil) (env env))
      (cond ((pair? p)
             (let ((v (cc:make-var (car p) lam)))
               (loop (cdr p) (cons v req) (cons (cons (car p) v) env))))
            (t
             (let ((rest (if (null? p) nil (cc:make-var p lam))))
               (vector-set! lam 0 (reverse req))
               (vector-set! lam 1 rest)
               (vector-set! lam 6 name)
               (if (> (+ (length req) (if rest 1 0)) 6) (cc:fail "too many parameters"))
               (vector-set! lam 2
                            (cc:x-body body (if rest (cons (cons p rest) env) env)))))))
    (set! cc:*owner* outer)
    (vector-set! lam 4 (cc:label))
    (vector-set! lam 5 (cc:label))
    (list 'lambda lam)))

(define (cc:x-named-let name bindings body env)
  (let* ((loopvar (cc:make-var name cc:*owner*))
         (lam (cc:x-lambda (cc:map car bindings) body (cons (cons name loopvar) env) name)))
    (list 'letrec (list loopvar) (list lam)
          (list 'call (list 'lref loopvar) (cc:map (lambda (b) (cc:x (cadr b) env)) bindings)))))

(define (cc:x-cond clauses env)
  (if (null? clauses)
      (list 'const nil)
      (let ((c (car clauses)) (rest (cc:x-cond (cdr clauses) env)))
        (if (null? (cdr c))
            (list 'or (cc:x (car c) env) rest)
            (list 'if (cc:x (car c) env) (cc:x-body (cdr c) env) rest)))))

; ======================================================================
; Free variables: each lambda's, for flat closures

; walk the AST; lams = the lambdas we're inside, innermost first
(define (cc:free n lams)
  (case (car n)
    ((const gref syntax-error) nil)
    ((lref) (cc:use (cadr n) lams))
    ((lset) (cc:use (cadr n) lams) (cc:free (caddr n) lams))
    ((gset) (cc:free (caddr n) lams))
    ((if and or seq) (cc:for-each (lambda (m) (cc:free m lams)) (cdr n)))
    ((let letrec)
     (cc:for-each (lambda (m) (cc:free m lams)) (caddr n))
     (cc:free (cadddr n) lams))
    ((lambda)
     (let ((lam (cadr n)))
       (cc:free (cc:lam-body lam) (cons lam lams))))
    ((call) (cc:free (cadr n) lams) (cc:for-each (lambda (m) (cc:free m lams)) (caddr n)))
    ((prim) (cc:for-each (lambda (m) (cc:free m lams)) (caddr n)))
    (t (error "cc: bad node" n))))

; a use of v: it's free in every lambda between the use and its owner
(define (cc:use v lams)
  (let loop ((l lams))
    (when (and (pair? l) (not (eq? (car l) (cc:var-owner v))))
      (vector-set! v 2 t)
      (vector-set! (car l) 3 (cc:adjoin v (cc:lam-free (car l))))
      (loop (cdr l)))))

; letrec variables bound to lambdas and never assigned are known functions
(define (cc:knowns n)
  (case (car n)
    ((const gref lref syntax-error) nil)
    ((lset gset) (cc:knowns (caddr n)))
    ((if and or seq) (cc:for-each cc:knowns (cdr n)))
    ((let) (cc:for-each cc:knowns (caddr n)) (cc:knowns (cadddr n)))
    ((letrec)
     (cc:each2 (lambda (v i)
                 (when (and (eq? (car i) 'lambda) (not (cc:var-assigned? v)))
                   (vector-set! v 5 (cadr i))))
               (cadr n) (caddr n))
     (cc:for-each cc:knowns (caddr n))
     (cc:knowns (cadddr n)))
    ((lambda) (cc:knowns (cc:lam-body (cadr n))))
    ((call) (cc:knowns (cadr n)) (cc:for-each cc:knowns (caddr n)))
    ((prim) (cc:for-each cc:knowns (caddr n)))
    (t nil)))

; ======================================================================
; Code generation
;
; Registers: r1 = the value of an expression; r3-r8 arguments; r2 the
; argument count at calls; r9 raw scratch (never a Lisp value across an
; allocation); r13 = nil, r14 = the heap pointer, r15 = sp.
; A function's frame: its arguments (SAVE r3-rN), its closure if it has
; free variables, then let-bound variables and temporaries, pushed as they
; come. A variable's frame index counts words from the frame's start;
; cc:*depth* is the number of words the frame holds now.

(define cc:*code* nil)          ; instructions, last first
(define cc:*depth* 0)
(define cc:*lam* nil)           ; the lambda being compiled
(define cc:*clo* nil)           ; the closure's frame index, or nil
(define cc:*stubs* nil)         ; (key label code) for this function's exits
(define cc:*pending* nil)       ; lambdas still to compile

; instructions carry a category, what they're for, which the profiles
; break compiled code's cycles down by (see cc:cat-names)
(define cc:*cats* nil)
(define cc:*cat* 'other)
(define (cc:emit i)
  (set! cc:*code* (cons i cc:*code*))
  (set! cc:*cats* (cons cc:*cat* cc:*cats*)))
(define (cc:e k i) (set! cc:*cat* k) (cc:emit i))
(define cc:cat-names
  '(other var global unbound const call entry return temp type pred arith overflow
    test alloc access bounds stub))
(define (cc:emit-label l) (cc:emit (list 'label l)))

(define (cc:rt name) (eval (cdr (assq name cc:rt-names))))
(define cc:rt-names
  '((cons . %rt:cons) (alloc . %rt:alloc) (gc . %rt:gc) (rest . %rt:rest) (num2 . %rt:num2)
    (notnum . %rt:notnum) (overflow . %rt:overflow) (unbound . %rt:unbound) (argc . %rt:argc)
    (notvec . %rt:notvec) (range . %rt:range) (syntax . %rt:syntax) (stack . %rt:stack)
    (cons-limit . %rt:cons-limit) (stack-limit . %rt:stack-limit) (t . %rt:t)))

(define (cc:off index) (* 4 (- cc:*depth* 1 index)))
(define (cc:push r) (cc:e 'temp (list 'st r '(pdec 15))) (set! cc:*depth* (+ cc:*depth* 1)))
(define (cc:pop r) (cc:e 'temp (list 'mov r '(pinc 15))) (set! cc:*depth* (- cc:*depth* 1)))
; leaving a scope that pushed down to depth d: pop it, unless a tail
; return has popped the whole frame already (the depth goes back either
; way, for the code that follows, an if's other branch say)
(define (cc:unbind d tail)
  (if tail
      (set! cc:*depth* d)
      (cc:drop (- cc:*depth* d))))

(define (cc:drop n)
  (when (> n 0)
    (cc:e 'temp (list 'add 15 (cc:imm (* 4 n))))
    (set! cc:*depth* (- cc:*depth* n))))

; a shared exit of this function: its label
(define (cc:stub key code)
  (let ((s (assoc key cc:*stubs*)))
    (if s
        (cadr s)
        (let ((l (cc:label)))
          (set! cc:*stubs* (cons (list key l code) cc:*stubs*))
          l))))

(define (cc:err-stub name) (cc:stub name (list (list 'rt 'ra (cc:rt name)))))
(define (cc:err3-stub name)            ; the irritant is r3
  (cc:stub (list name 3) (list (list 'mov 1 '(reg 3)) (list 'rt 'ra (cc:rt name)))))

(define (cc:t-imm) (cc:imm (cc:rt 't)))

; ---- variables

; where v's value is, in this function: an operand for its slot or box
(define (cc:load-var v r)
  (if (eq? (cc:var-owner v) cc:*lam*)
      (cc:e 'var (list 'mov r (list 'mem 15 (cc:off (cc:var-index v)))))
      (begin
        (cc:e 'var (list 'mov r (list 'mem 15 (cc:off cc:*clo*))))
        (cc:e 'var (list 'mov r (list 'mem r (+ 5 (* 4 (cc:index v (cc:lam-free cc:*lam*)))))))))
  (if (cc:boxed? v) (cc:e 'var (list 'mov r (list 'mem r -1)))))

(define (cc:store-var v)               ; r1 -> v (uses r3 for a box)
  (cond ((cc:boxed? v)
         (cc:load-box v 3)
         (cc:e 'var '(st 1 (mem 3 -1))))
        ((eq? (cc:var-owner v) cc:*lam*)
         (cc:e 'var (list 'st 1 (list 'mem 15 (cc:off (cc:var-index v))))))
        (t (error "cc: assigning a captured variable without a box" v))))

(define (cc:load-box v r)              ; the box itself, not its contents
  (if (eq? (cc:var-owner v) cc:*lam*)
      (cc:e 'var (list 'mov r (list 'mem 15 (cc:off (cc:var-index v)))))
      (begin
        (cc:e 'var (list 'mov r (list 'mem 15 (cc:off cc:*clo*))))
        (cc:e 'var (list 'mov r (list 'mem r (+ 5 (* 4 (cc:index v (cc:lam-free cc:*lam*))))))))))

; bind v to r1 at the top of the frame (boxing it if it needs a box)
(define (cc:bind-var v)
  (when (cc:boxed? v)
    (cc:e 'alloc '(mov 3 (reg 1)))
    (cc:e 'alloc '(mov 4 (reg 13)))
    (cc:gen-cons))
  (vector-set! v 4 cc:*depth*)
  (cc:push 1))

; ---- constants

(define (cc:const-operand x)
  (cond ((integer? x)
         (cc:fix x))
        ((%address x) (cc:imm (%address x)))
        (t (let ((c (%static-copy x)))
             (if (null? c)
                 (begin (cc:fail "a constant that can't be copied") (cc:imm 0))
                 (cc:imm (%address c)))))))

(define (cc:load-const x r)
  (if (null? x)
      (cc:e 'const (list 'mov r '(reg 13)))
      (cc:e 'const (list 'mov r (cc:const-operand x)))))

; ---- expressions: value in r1; tail: return it (or tail-call)

(define (cc:ret tail)
  (when tail
    (cc:emit-frame-pop)
    (cc:e 'return '(ret))))

(define (cc:emit-frame-pop)            ; pop the frame without changing cc:*depth*
  (when (> cc:*depth* 0) (cc:e 'return (list 'add 15 (cc:imm (* 4 cc:*depth*))))))

(define (cc:g n tail)
  (case (car n)
    ((const) (cc:load-const (cadr n) 1) (cc:ret tail))
    ((lref) (cc:load-var (cadr n) 1) (cc:ret tail))
    ((gref) (cc:load-global (cadr n)) (cc:ret tail))
    ((lset) (cc:g (caddr n) nil) (cc:store-var (cadr n)) (cc:ret tail))
    ((gset)
     (cc:g (caddr n) nil)
     (cc:e 'global (list 'st 1 (list 'abs (+ (%address (cadr n)) 5))))
     (cc:ret tail))
    ((if)
     (let ((else (cc:label)) (end (cc:label)))
       (cc:test (cadr n) else)
       (cc:g (caddr n) tail)
       (unless tail (cc:e 'test (list 'b 'ra end)))
       (cc:emit-label else)
       (cc:g (cadddr n) tail)
       (cc:emit-label end)))
    ((and)
     (let ((false (cc:label)) (end (cc:label)))
       (let loop ((l (cdr n)))
         (if (null? (cdr l))
             (cc:g (car l) tail)
             (begin (cc:test (car l) false) (loop (cdr l)))))
       (unless tail (cc:e 'test (list 'b 'ra end)))
       (cc:emit-label false)
       (cc:e 'test '(mov 1 (reg 13)))
       (cc:ret tail)
       (cc:emit-label end)))
    ((or)
     (let ((end (cc:label)))
       (let loop ((l (cdr n)))
         (if (null? (cdr l))
             (cc:g (car l) tail)
             (begin
               (cc:g (car l) nil)
               (cc:e 'test '(cmp 1 (reg 13)))
               (if tail
                   (let ((next (cc:label)))
                     (cc:e 'test (list 'b 'eq next))
                     (cc:ret t)
                     (cc:emit-label next))
                   (cc:e 'test (list 'b 'ne end)))
               (loop (cdr l)))))
       (cc:emit-label end)))
    ((seq)
     (let loop ((l (cdr n)))
       (if (null? (cdr l))
           (cc:g (car l) tail)
           (begin (cc:g (car l) nil) (loop (cdr l))))))
    ((let)
     (let ((d cc:*depth*))
       (cc:each2 (lambda (v i) (cc:g i nil) (cc:bind-var v)) (cadr n) (caddr n))
       (cc:g (cadddr n) tail)
       (cc:unbind d tail)))
    ((letrec) (cc:g-letrec n tail))
    ((lambda) (cc:g-lambda (cadr n)) (cc:ret tail))
    ((call) (cc:g-call (cadr n) (caddr n) tail))
    ((prim) (cc:g-prim (cadr n) (caddr n)) (cc:ret tail))
    ((syntax-error)
     (cc:load-const (cadr n) 1)
     (cc:e 'stub (list 'rt 'ra (cc:rt 'syntax))))
    (t (error "cc: bad node" n))))

(define (cc:load-global s)
  (cc:e 'global (list 'mov 1 (list 'abs (+ (%address s) 5))))
  (cc:e 'unbound (list 'cmp 1 (cc:imm 1)))
  (cc:e 'unbound (list 'b 'eq (cc:stub (list 'unbound s)
                                  (list (list 'mov 1 (cc:imm (%address s)))
                                        (list 'rt 'ra (cc:rt 'unbound)))))))

; ---- tests: jump to false if the value is nil

(define (cc:test n false)
  (cond ((eq? (car n) 'prim) (cc:test-prim (cadr n) (caddr n) false))
        ((eq? (car n) 'and) (cc:for-each (lambda (m) (cc:test m false)) (cdr n)))
        ((eq? (car n) 'or)
         (let ((true (cc:label)))
           (let loop ((l (cdr n)))
             (if (null? (cdr l))
                 (cc:test (car l) false)
                 (let ((next (cc:label)))
                   (cc:test (car l) next)
                   (cc:e 'test (list 'b 'ra true))
                   (cc:emit-label next)
                   (loop (cdr l)))))
           (cc:emit-label true)))
        ((eq? (car n) 'const)
         (if (null? (cadr n)) (cc:e 'test (list 'b 'ra false))))
        (t (cc:g n nil)
           (cc:e 'test '(cmp 1 (reg 13)))
           (cc:e 'test (list 'b 'eq false)))))

; ---- lambda: a closure

(define (cc:g-lambda lam)
  (set! cc:*pending* (cons lam cc:*pending*))
  (let ((free (cc:lam-free lam)))
    (if (null? free)
        (let ((c (%static-closure 0)))  ; the code address is patched in later
          (vector-set! lam 7 c)
          (cc:e 'const (list 'mov 1 (cc:imm (%address c)))))
        (let ((k (length free)))
          (cc:e 'alloc (list 'mov 2 (cc:imm (logand (+ 8 (* 4 k) 7) -8))))
          (cc:e 'alloc (list 'rt 'call (cc:rt 'alloc)))
          (cc:e 'alloc (list 'mov 9 (cc:imm (+ (* (+ 1 k) 256) 37))))   ; header: B_CLO
          (cc:e 'alloc '(st 9 (mem 1 0)))
          (cc:e 'alloc (list 'lea 9 (list 'pcrel (cc:lam-entry lam))))
          (cc:e 'alloc '(st 9 (mem 1 4)))
          (let loop ((l free) (i 0))
            (when (pair? l)
              (cc:load-box-or-value (car l) 9)
              (cc:e 'alloc (list 'st 9 (list 'mem 1 (+ 8 (* 4 i)))))
              (loop (cdr l) (+ i 1))))
          (cc:e 'alloc '(or 1 (imm 0 3)))))))

; what a closure captures: the box, if the variable has one, else its value
(define (cc:load-box-or-value v r)
  (if (cc:boxed? v) (cc:load-box v r) (cc:load-var v r)))

; ---- letrec

(define (cc:g-letrec n tail)
  (let ((vars (cadr n)) (inits (caddr n)) (d cc:*depth*))
    ; every variable gets its slot (or box) first, holding nil
    (cc:for-each (lambda (v) (cc:e 'var '(mov 1 (reg 13))) (cc:bind-var v)) vars)
    (let loop ((vs vars) (is inits) (done nil))
      (when (pair? vs)
        (let ((v (car vs)) (i (car is)))
          (cc:g i nil)
          (if (cc:boxed? v)
              (cc:store-var v)
              (cc:e 'var (list 'st 1 (list 'mem 15 (cc:off (cc:var-index v))))))
          ; closures made so far that captured a variable's value before it
          ; had one get it now (boxed variables need nothing: closures share
          ; the box)
          (let ((done (cons (cons v i) done)))
            (cc:patch-letrec done)
            (loop (cdr vs) (cdr is) done)))))
    (cc:g (cadddr n) tail)
    (cc:unbind d tail)))

; for every (var . init) done whose init is a lambda with free variables,
; store the current values of the done, unboxed variables it captures
(define (cc:patch-letrec done)
  (cc:for-each
   (lambda (vi)
     (let ((i (cdr vi)))
       (when (and (eq? (car i) 'lambda) (pair? (cc:lam-free (cadr i))))
         (let ((free (cc:lam-free (cadr i))))
           (cc:for-each
            (lambda (wi)
              (let ((w (car wi)) (k (cc:index (car wi) free)))
                (when (and k (not (cc:boxed? w)))
                  (cc:load-var (car vi) 3)
                  (cc:load-var w 9)
                  (cc:e 'alloc (list 'st 9 (list 'mem 3 (+ 5 (* 4 k))))))))
            done)))))
   done))

; ---- calls

(define (cc:simple? n)
  (or (eq? (car n) 'const)
      (and (eq? (car n) 'lref) (not (cc:var-assigned? (cadr n))))))

; evaluate args left to right into registers regs: the complex ones first,
; onto the stack; then the simple ones are loaded and the others popped.
(define (cc:args-into args regs)
  (cc:for-each (lambda (a) (unless (cc:simple? a) (cc:g a nil) (cc:push 1))) args)
  (cc:each2 (lambda (a r)
              (when (cc:simple? a)
                (if (eq? (car a) 'const) (cc:load-const (cadr a) r) (cc:load-var (cadr a) r))))
            args regs)
  (cc:each2 (lambda (a r) (unless (cc:simple? a) (cc:pop r)))
            (reverse args) (reverse regs)))

(define cc:arg-regs '(3 4 5 6 7 8))

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
               (begin (cc:emit-frame-pop) (cc:e 'call '(jmpea (mem 1 1))))
               (cc:e 'call '(callea (mem 1 1))))))))

(define (cc:arity-ok? lam n)
  (let ((req (length (cc:lam-req lam))))
    (if (cc:lam-rest lam) (>= n req) (= n req))))

; a call to a letrec-bound lambda: straight to its body, past the check of
; the argument count; a tail call to itself is a jump
(define (cc:known-call lam n tail)
  (if (cc:lam-rest lam) (cc:e 'call (list 'mov 2 (cc:imm n))))
  (if tail
      (begin (cc:emit-frame-pop) (cc:e 'call (list 'b 'ra (cc:lam-start lam))))
      (cc:e 'call (list 'bsr (cc:lam-start lam)))))

; more than 6 arguments: 1-5 in r3-r7, a list of the rest in r8
(define (cc:many-args args)
  (cc:for-each (lambda (a) (cc:g a nil) (cc:push 1)) args)
  (cc:e 'call '(mov 4 (reg 13)))
  (let loop ((k (- (length args) 5)))
    (when (> k 0)
      (cc:pop 3)
      (cc:e 'call (list 'rt 'call (cc:rt 'cons)))
      (cc:e 'call '(mov 4 (reg 1)))
      (loop (- k 1))))
  (cc:e 'call '(mov 8 (reg 4)))
  (cc:for-each (lambda (r) (cc:pop r)) '(7 6 5 4 3)))

(define (cc:filter f l)
  (cond ((null? l) nil) ((f (car l)) (cons (car l) (cc:filter f (cdr l)))) (t (cc:filter f (cdr l)))))
(define (cc:take l n) (if (= n 0) nil (cons (car l) (cc:take (cdr l) (- n 1)))))

; ---- primitives

(define (cc:gen-cons)                  ; r3 = car, r4 = cdr -> r1
  (let ((back (cc:label)))
    (cc:e 'alloc (list 'cmp 14 (list 'abs (cc:rt 'cons-limit))))
    (cc:e 'alloc (list 'b 'hi (cc:stub (list 'gc back)
                                   (list (list 'rt 'call (cc:rt 'gc)) (list 'b 'ra back)))))
    (cc:emit-label back)
    (cc:e 'alloc '(st 3 (pinc 14)))
    (cc:e 'alloc '(st 4 (pinc 14)))
    (cc:e 'alloc '(lea 1 (mem 14 -7)))))

(define (cc:check-num r)               ; r is a fixnum, else "not a number"
  (if (cc:option? 'tagged)
      (cc:e 'type (list 'mov 9 (list 'tag r)))
      (cc:check-num-sw r)))

(define (cc:check-num-sw r)
  (cc:e 'type (list 'mov 9 (list 'reg r)))
  (cc:e 'type '(and 9 (imm 0 1)))
  (cc:e 'type (list 'b 'ne (if (= r 1) (cc:err-stub 'notnum) (cc:err3-stub 'notnum)))))

(define (cc:check-num2)                ; r1 and r3
  (if (cc:option? 'tagged)
      (cc:e 'type '(cmp 1 (tag 3)))
      (cc:check-num2-sw)))

(define (cc:check-num2-sw)
  (cc:e 'type '(mov 9 (reg 1)))
  (cc:e 'type '(or 9 (reg 3)))
  (cc:e 'type '(and 9 (imm 0 1)))
  (cc:e 'type (list 'b 'ne (cc:err-stub 'num2))))

; a fixnum constant second operand?
(define (cc:small-const? a)
  (and (eq? (car a) 'const) (integer? (cadr a))
       (>= (cadr a) -16384) (<= (cadr a) 16383)))

; two number operands: r1, and either a constant (returned as an operand)
; or r3 (returns (reg 3)); both checked
(define (cc:num-args args)
  (cond ((cc:option? 'tagged)          ; checked by the instruction itself
         (cc:args-into args '(1 3))
         '(tag 3))
        (t (cc:num-args-sw args))))

(define (cc:num-args-sw args)
  (if (cc:small-const? (cadr args))
      (begin (cc:g (car args) nil) (cc:check-num 1) (cc:fix (cadr (cadr args))))
      (begin (cc:args-into args '(1 3)) (cc:check-num2) '(reg 3))))

(define (cc:g-prim name args)
  (case name
    ((car) (cc:g (car args) nil) (cc:e 'access '(mov 1 (mem 1 -1))))
    ((cdr) (cc:g (car args) nil) (cc:e 'access '(mov 1 (mem 1 3))))
    ((caar cadr cdar cddr caddr cdddr cadddr)
     (cc:g (car args) nil)
     (cc:for-each (lambda (d) (cc:e 'access (list 'mov 1 (list 'mem 1 d))))
                  (cdr (assq name '((caar -1 -1) (cadr 3 -1) (cdar -1 3) (cddr 3 3)
                                    (caddr 3 3 -1) (cdddr 3 3 3) (cadddr 3 3 3 -1))))))
    ((cons) (cc:args-into args '(3 4)) (cc:gen-cons))
    ((set-car!) (cc:args-into args '(3 4)) (cc:e 'access '(st 4 (mem 3 -1))) (cc:e 'access '(mov 1 (reg 4))))
    ((set-cdr!) (cc:args-into args '(3 4)) (cc:e 'access '(st 4 (mem 3 3))) (cc:e 'access '(mov 1 (reg 4))))
    ((+)
     (let ((o (cc:num-args args)))
       (cc:e 'arith (list 'add 1 o))
       (unless (eq? (car o) 'tag) (cc:e 'overflow (list 'b 'vs (cc:err-stub 'overflow))))))
    ((-)
     (if (null? (cdr args))
         (begin (cc:g (car args) nil) (cc:check-num 1)
                (cc:e 'arith '(unary neg 1 1))
                (cc:e 'overflow (list 'b 'vs (cc:err-stub 'overflow))))
         (let ((o (cc:num-args args)))
           (cc:e 'arith (list 'sub 1 o))
           (unless (eq? (car o) 'tag) (cc:e 'overflow (list 'b 'vs (cc:err-stub 'overflow)))))))
    ((*)
     (cc:args-into args '(1 3))
     (cc:check-num2)
     (cc:e 'arith '(shift asr 1 1))
     (cc:e 'arith '(rr muls 1 3))
     (cc:e 'overflow (list 'b 'vs (cc:err-stub 'overflow))))
    ((vector-ref)
     (cc:args-into args '(1 3))
     (cc:check-vector-index)
     (cc:e 'access '(mov 1 (idx 1 3 2 5 word))))
    ((vector-set!)
     (cc:args-into args '(1 3 4))
     (cc:check-vector-index)
     (cc:e 'access '(st 4 (idx 1 3 2 5 word)))
     (cc:e 'access '(mov 1 (reg 4))))
    ((vector-length)
     (cc:g (car args) nil)
     (cc:check-vector)
     (cc:e 'access '(mov 1 (mem 1 -3)))
     (cc:e 'access '(shift lsr 1 7))
     (cc:e 'access '(and 1 (imm 65535 65534)))
     (cc:e 'access '(sub 1 (imm 0 2))))       ; (the size counts the call slot)
    (t (cc:g-bool name args))))

(define (cc:check-vector)              ; r1 is a vector
  (let ((bad (cc:err-stub 'notvec)))
    (cc:e 'type '(mov 9 (reg 1)))
    (cc:e 'type '(and 9 (imm 0 3)))
    (cc:e 'type '(cmp 9 (imm 0 3)))
    (cc:e 'type (list 'b 'ne bad))
    (cc:e 'type '(mov 9 (byte 1 -3)))
    (cc:e 'type '(cmp 9 (imm 0 21)))      ; B_VEC
    (cc:e 'type (list 'b 'ne bad))))

(define (cc:check-vector-index)        ; r1 a vector, r3 an index in it
  (cc:check-vector)
  (cc:check-num 3)
  (cc:e 'bounds '(mov 9 (mem 1 -3)))
  (cc:e 'bounds '(shift lsr 9 7))
  (cc:e 'bounds '(and 9 (imm 65535 65534)))
  (cc:e 'bounds '(sub 9 (imm 0 2)))
  (cc:e 'bounds '(cmp 3 (reg 9)))
  (cc:e 'bounds (list 'b 'hs (cc:err3-stub 'range))))

; an expression that cc:test compiles to branches without making a value
(define (cc:testable? n)
  (and (eq? (car n) 'prim)
       (memq (cadr n) '(not null? eq? pair? atom? number? integer? symbol? zero? = < > <= >=))))

; predicates and comparisons for their value: t or nil
(define (cc:g-bool name args)
  (let ((false (cc:label)) (end (cc:label)))
    (cc:test-prim name args false)
    (cc:e 'test (list 'mov 1 (cc:t-imm)))
    (cc:e 'test (list 'b 'ra end))
    (cc:emit-label false)
    (cc:e 'test '(mov 1 (reg 13)))
    (cc:emit-label end)))

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
     (cc:e 'pred '(mov 9 (reg 1)))
     (cc:e 'pred '(and 9 (imm 0 1)))
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
         (cc:e 'arith '(cmp 1 (tag 0)))
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

(define (cc:g-function lam)
  (set! cc:*lam* lam)
  (set! cc:*stubs* nil)
  (let* ((req (cc:lam-req lam))
         (rest (cc:lam-rest lam))
         (params (if rest (append req (list rest)) req))
         (np (length params))
         (nreq (length req)))
    (cc:emit-label (cc:lam-entry lam))
    (cc:e 'entry (list 'cmp 2 (cc:imm nreq)))
    (cc:e 'entry (list 'b (if rest 'lo 'ne) (cc:err-stub 'argc)))
    (cc:emit-label (cc:lam-start lam))
    (cc:e 'entry (list 'cmp 15 (list 'abs (cc:rt 'stack-limit))))
    (cc:e 'entry (list 'b 'lo (cc:err-stub 'stack)))
    (when rest
      (cc:e 'entry (list 'mov 9 (cc:imm nreq)))
      (cc:e 'entry (list 'rt 'call (cc:rt 'rest)))
      (cc:e 'entry (list 'mov (+ 3 nreq) '(reg 12))))
    (set! cc:*depth* 0)
    (when (> np 0)
      (cc:e 'entry (list 'save 3 (+ 2 np)))
      (set! cc:*depth* np))
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
                 (reverse cc:*stubs*))))

(define (cc:load-var-raw v r)          ; a parameter's slot, before it has its box
  (cc:e 'alloc (list 'mov r (list 'mem 15 (cc:off (cc:var-index v))))))

; ======================================================================
; The driver

; compile a form as a function of no arguments -> its static closure, or
; nil if it couldn't be compiled
(define (cc:compile form)
  (set! cc:*fail* nil)
  (set! cc:*owner* nil)
  (let* ((top (cc:x-lambda nil (list form) nil nil))
         (lam (cadr top)))
    (if cc:*fail*
        nil
        (begin
          (cc:free (cc:lam-body lam) (list lam))
          (cc:knowns (cc:lam-body lam))
          (set! cc:*code* nil)
          (set! cc:*cats* nil)
          (set! cc:*pending* (list lam))
          (set! cc:*all-lams* nil)
          (let ((c (%make-closure 0 0)))   ; (its code address is set below)
            (let loop ()
              (when (pair? cc:*pending*)
                (let ((l (car cc:*pending*)))
                  (set! cc:*pending* (cdr cc:*pending*))
                  (set! cc:*all-lams* (cons l cc:*all-lams*))
                  (cc:g-function l)
                  (loop))))
            (if cc:*fail*
                nil
                (let ((labels (cc:install (reverse cc:*code*) (reverse cc:*cats*))))
                  ; the form's own closure is in the heap: nothing refers to it
                  (%closure-set-code! c (cc:label-addr (cc:lam-entry lam) labels))
                  c)))))))

; assemble and install: patch the static closures with their code
(define (cc:install insns cats)
  (let* ((base (%code-free))
         (r (cc:asm insns base cats))
         (parcels (car r))
         (labels (cadr r))
         (addr (%code-alloc (* 2 (length parcels))))
         (code-base %rt:code-base)
         (catmap %rt:catmap)
         (catmap-end %rt:catmap-end))
    (unless (= addr base) (error "cc: code space moved" addr base))
    (let loop ((p parcels) (a addr) (cs (caddr r)))
      (when (pair? p)
        (%poke16 a (car p))
        (let ((m (+ catmap (quotient (- a code-base) 2))))
          (if (< m catmap-end) (%poke8 m (cc:index (car cs) cc:cat-names))))
        (loop (cdr p) (+ a 2) (cdr cs))))
    (cc:patch-statics insns labels)
    labels))

; every (mov r (imm ...)) of a static closure was emitted by cc:g-lambda;
; the lambdas are found again through the labels
(define (cc:patch-statics insns labels)
  (cc:for-each (lambda (lam)
                 (let ((c (cc:lam-static lam)))
                   (when c
                     (let ((a (+ (%address c) 1))
                           (code (cc:label-addr (cc:lam-entry lam) labels)))
                       (%poke16 a (cc:u16 code))
                       (%poke16 (+ a 2) (cc:u16 (ash code -16)))))))
               cc:*all-lams*))

(define cc:*all-lams* nil)

; the top level: compile each form and run it, or evaluate it if it can't
; be compiled
(define (cc:toplevel form)
  (let ((f (cc:compile form)))
    (if f
        (begin (%run-begin) (let ((v (f))) (%run-end) v))
        (eval form))))

; (cc:show 'form): print the instructions the compiler makes for a form,
; without installing them. A debugging aid.
(define (cc:show form)
  (set! cc:*fail* nil)
  (set! cc:*owner* nil)
  (let* ((top (cc:x-lambda nil (list form) nil nil)) (lam (cadr top)))
    (cc:free (cc:lam-body lam) (list lam))
    (cc:knowns (cc:lam-body lam))
    (set! cc:*code* nil)
    (set! cc:*pending* (list lam))
    (let loop ()
      (when (pair? cc:*pending*)
        (let ((l (car cc:*pending*)))
          (set! cc:*pending* (cdr cc:*pending*))
          (cc:g-function l)
          (loop))))
    (for-each (lambda (i)
                (unless (eq? (car i) 'label) (display "        "))
                (write i) (newline))
              (reverse cc:*code*))
    cc:*fail*))
