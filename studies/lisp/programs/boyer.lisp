; BOYER: a rewrite-rule tautology checker in the style of Gabriel's BOYER
; (after the Boyer-Moore prover). Not the original: a smaller lemma set,
; written for this language, with the same structure. Lemmas are stored on
; the property list of the function symbol they rewrite (put/get), terms
; are rewritten bottom-up by one-way unification against the lemmas, and
; the result, in if-normal form, is checked for being a tautology by case
; splitting on the tests.
;
; Exercises: symbolic code, property lists, assq association lists, eq?
; and equal? on terms, set! on a global, deep recursion over terms,
; garbage.

(define (add-lemma term)
  (if (and (pair? term) (eq? (car term) 'equal) (pair? (cadr term)))
      (let ((f (car (cadr term))))
        (put f 'lemmas (cons term (get f 'lemmas))))
      (error "not a lemma" term)))

(define (add-lemmas l) (for-each add-lemma l))

(add-lemmas
 '((equal (and p q) (if p (if q (t) (f)) (f)))
   (equal (or p q) (if p (t) (if q (t) (f))))
   (equal (not p) (if p (f) (t)))
   (equal (implies p q) (if p (if q (t) (f)) (t)))
   (equal (iff p q) (and (implies p q) (implies q p)))
   (equal (if (if a b c) d e) (if a (if b d e) (if c d e)))
   (equal (greaterp x y) (lessp y x))
   (equal (lesseqp x y) (not (lessp y x)))
   (equal (greatereqp x y) (not (lessp x y)))
   (equal (zerop x) (or (equal x (zero)) (not (numberp x))))
   (equal (fix x) (if (numberp x) x (zero)))
   (equal (plus (plus x y) z) (plus x (plus y z)))
   (equal (plus x (zero)) (fix x))
   (equal (times (times x y) z) (times x (times y z)))
   (equal (times x (plus y z)) (plus (times x y) (times x z)))
   (equal (times x (zero)) (zero))
   (equal (difference x x) (zero))
   (equal (append (append x y) z) (append x (append y z)))
   (equal (append (empty) x) x)
   (equal (reverse (append a b)) (append (reverse b) (reverse a)))
   (equal (reverse (empty)) (empty))
   (equal (length (reverse x)) (length x))
   (equal (length (append a b)) (plus (length a) (length b)))
   (equal (member x (append a b)) (or (member x a) (member x b)))
   (equal (member x (reverse y)) (member x y))
   (equal (remainder x x) (zero))
   (equal (remainder x 1) (zero))
   (equal (lessp (remainder x y) y) (not (zerop y)))
   (equal (equal (plus a b) (zero)) (and (zerop a) (zerop b)))
   (equal (equal (times x y) (zero)) (or (zerop x) (zerop y)))
   (equal (equal (append a b) (append a c)) (equal b c))
   (equal (count-list z (append x y)) (plus (count-list z x) (count-list z y)))))

; ---- one-way unification and rewriting

(define unify-subst nil)

(define (one-way-unify term1 term2)
  (set! unify-subst nil)
  (unify1 term1 term2))

(define (unify1 term1 term2)
  (cond ((not (pair? term2))
         (let ((b (assq term2 unify-subst)))
           (if b
               (equal? term1 (cdr b))
               (begin (set! unify-subst (cons (cons term2 term1) unify-subst)) t))))
        ((not (pair? term1)) nil)
        ((eq? (car term1) (car term2)) (unify1-list (cdr term1) (cdr term2)))
        (t nil)))

(define (unify1-list l1 l2)
  (cond ((null? l1) (null? l2))
        ((null? l2) nil)
        ((unify1 (car l1) (car l2)) (unify1-list (cdr l1) (cdr l2)))
        (t nil)))

(define (apply-subst alist term)
  (if (pair? term)
      (cons (car term) (apply-subst-list alist (cdr term)))
      (let ((b (assq term alist)))
        (if b (cdr b) term))))

(define (apply-subst-list alist l)
  (if (null? l)
      nil
      (cons (apply-subst alist (car l)) (apply-subst-list alist (cdr l)))))

(define (rewrite term)
  (if (pair? term)
      (rewrite-with-lemmas (cons (car term) (rewrite-args (cdr term)))
                           (get (car term) 'lemmas))
      term))

(define (rewrite-args l)
  (if (null? l)
      nil
      (cons (rewrite (car l)) (rewrite-args (cdr l)))))

(define (rewrite-with-lemmas term lemmas)
  (cond ((null? lemmas) term)
        ((one-way-unify term (cadr (car lemmas)))
         (rewrite (apply-subst unify-subst (caddr (car lemmas)))))
        (t (rewrite-with-lemmas term (cdr lemmas)))))

; ---- the tautology checker, on if-normal terms

(define (truep x l) (or (equal? x '(t)) (member x l)))
(define (falsep x l) (or (equal? x '(f)) (member x l)))

(define (tautologyp x true-l false-l)
  (cond ((truep x true-l) t)
        ((falsep x false-l) nil)
        ((not (pair? x)) nil)
        ((eq? (car x) 'if)
         (cond ((truep (cadr x) true-l) (tautologyp (caddr x) true-l false-l))
               ((falsep (cadr x) false-l) (tautologyp (cadddr x) true-l false-l))
               (t (and (tautologyp (caddr x) (cons (cadr x) true-l) false-l)
                       (tautologyp (cadddr x) true-l (cons (cadr x) false-l))))))
        (t nil)))

(define (tautp x) (tautologyp (rewrite x) nil nil))

(define (term-size x)
  (if (pair? x) (+ 1 (term-size (car x)) (term-size (cdr x))) 0))

; ---- the problems

(define bindings
  '((x f (plus (plus a b) (plus c (zero))))
    (y f (times (times a b) (plus c d)))
    (z f (reverse (append (append a b) (empty))))
    (w lessp (remainder a b) (member a (length b)))))

; transitivity of implication, through four terms: a tautology
(define chain
  (apply-subst bindings
               '(implies (and (implies x y)
                              (and (implies y z)
                                   (implies z w)))
                         (implies x w))))

; three terms, with the conclusion reversed: not a tautology
(define broken
  (apply-subst bindings
               '(implies (and (implies x y)
                              (implies y z))
                         (implies z x))))

(define (run n)
  (let loop ((i 0) (r nil))
    (if (= i n)
        r
        (loop (+ i 1) (list (tautp chain) (tautp broken))))))

(display "results: ")
(write (run 2))
(newline)
(display "size of the chain, before and after rewriting: ")
(write (list (term-size chain) (term-size (rewrite chain))))
(newline)
(display "rewriting (reverse (append (append a b) (empty))): ")
(write (rewrite '(reverse (append (append a b) (empty)))))
(newline)
