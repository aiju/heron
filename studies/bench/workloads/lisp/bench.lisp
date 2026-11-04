; The Lisp workload's program: a little of everything Lisp programs do,
; each part folding its results into a number that is printed at the end.
; Everything above "the run" is loaded into the saved image the workload
; starts from; the run (below it) is the console input, after `n`, which
; scales every part.

; ---- a pseudo-random sequence, the same on every run ----

(define seed 12345)
(define (random k)
  (set! seed (logand (+ (* seed 1103) 12345) 65535))
  (remainder seed k))

; ---- symbolic differentiation (Gabriel's DERIV): cons and the collector ----

(define (deriv-aux a) (list '/ (deriv a) a))
(define (deriv a)
  (cond ((not (pair? a)) (if (eq? a 'x) 1 0))
        ((eq? (car a) '+) (cons '+ (map deriv (cdr a))))
        ((eq? (car a) '-) (cons '- (map deriv (cdr a))))
        ((eq? (car a) '*) (list '* a (cons '+ (map deriv-aux (cdr a)))))
        ((eq? (car a) '/)
         (list '- (list '/ (deriv (cadr a)) (caddr a))
               (list '/ (cadr a) (list '* (caddr a) (caddr a) (deriv (caddr a))))))
        (t (error "no derivation method for" (car a)))))

(define (count-pairs x)
  (if (pair? x) (+ 1 (count-pairs (car x)) (count-pairs (cdr x))) 0))

(define (deriv-part k)
  (let loop ((i 0) (sum 0))
    (if (= i k)
        sum
        (loop (+ i 1)
              (+ sum (count-pairs (deriv '(+ (* 3 x) (* b x) 5))))))))

; ---- sorting a list: merge sort, recursion on lists ----

(define (merge a b)
  (cond ((null? a) b)
        ((null? b) a)
        ((< (car a) (car b)) (cons (car a) (merge (cdr a) b)))
        (t (cons (car b) (merge a (cdr b))))))

(define (split l)
  (if (or (null? l) (null? (cdr l)))
      (list l nil)
      (let ((rest (split (cddr l))))
        (list (cons (car l) (car rest)) (cons (cadr l) (cadr rest))))))

(define (msort l)
  (if (or (null? l) (null? (cdr l)))
      l
      (let ((halves (split l)))
        (merge (msort (car halves)) (msort (cadr halves))))))

(define (random-list k)
  (let loop ((i 0) (acc nil))
    (if (= i k) acc (loop (+ i 1) (cons (random 10000) acc)))))

(define (weigh l)                       ; position-weighted sum: checks the order
  (let loop ((l l) (i 1) (sum 0))
    (if (null? l) sum (loop (cdr l) (+ i 1) (logand (+ sum (* i (car l))) 268435455)))))

(define (sort-part k) (weigh (msort (random-list k))))

; ---- higher-order procedures and closures ----

(define (fold f acc l) (if (null? l) acc (fold f (f acc (car l)) (cdr l))))
(define (filter p l)
  (cond ((null? l) nil) ((p (car l)) (cons (car l) (filter p (cdr l)))) (t (filter p (cdr l)))))
(define (iota k) (let loop ((i k) (acc nil)) (if (= i 0) acc (loop (- i 1) (cons i acc)))))
(define (compose f g) (lambda (x) (f (g x))))
(define (adder k) (lambda (x) (+ x k)))
(define (make-counter)
  (let ((count 0)) (lambda () (set! count (+ count 1)) count)))

(define (closure-part k)
  (let ((c (make-counter))
        (f (compose (adder 3) (lambda (x) (* x 2)))))
    (let loop ((i 0) (sum 0))
      (if (= i k)
          (+ sum (c))
          (begin
            (c)
            (loop (+ i 1)
                  (+ sum (fold + 0 (map f (filter (lambda (x) (= (remainder x 3) 0))
                                                  (iota 12)))))))))))

; ---- symbols and property lists: a symbol table ----

(define words '(alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu))

(define (plist-part k)
  (let loop ((i 0) (sum 0))
    (if (= i k)
        sum
        (begin
          (for-each (lambda (w)
                      (put w 'count (+ 1 (or (get w 'count) 0)))
                      (put w 'len (string-length (symbol->string w))))
                    words)
          (loop (+ i 1)
                (fold (lambda (s w) (+ s (* (get w 'count) (get w 'len)))) sum words))))))

; ---- vectors: a sieve ----

(define (sieve k)
  (let ((v (make-vector k t)))
    (let outer ((i 2) (count 0))
      (cond ((= i k) count)
            ((vector-ref v i)
             (let inner ((j (+ i i)))
               (if (< j k) (begin (vector-set! v j nil) (inner (+ j i)))))
             (outer (+ i 1) (+ count 1)))
            (t (outer (+ i 1) count))))))

; ---- a small evaluator: an interpreter interpreted ----

(define (lookup x env)
  (let ((b (assq x env))) (if b (cdr b) (error "unbound" x))))

(define (ev e env)
  (cond ((number? e) e)
        ((symbol? e) (lookup e env))
        ((eq? (car e) 'add) (+ (ev (cadr e) env) (ev (caddr e) env)))
        ((eq? (car e) 'mul) (* (ev (cadr e) env) (ev (caddr e) env)))
        ((eq? (car e) 'sub) (- (ev (cadr e) env) (ev (caddr e) env)))
        ((eq? (car e) 'if0) (if (= (ev (cadr e) env) 0) (ev (caddr e) env) (ev (cadddr e) env)))
        ((eq? (car e) 'let1)
         (ev (cadddr e) (cons (cons (cadr e) (ev (caddr e) env)) env)))
        (t (error "bad expression" e))))

(define program
  '(let1 a 7
     (let1 b (mul a 3)
       (if0 (sub b 21)
            (add (mul a b) (let1 c (add a 1) (mul c c)))
            0))))

(define (eval-part k)
  (let loop ((i 0) (sum 0))
    (if (= i k)
        sum
        (loop (+ i 1) (+ sum (ev program (list (cons 'z i))))))))

; ---- the run ----

(define (report name value) (display name) (write-char 32) (display value) (newline))

(define r-deriv (deriv-part n))
(define r-sort (sort-part (* 4 n)))
(define r-closure (closure-part n))
(define r-plist (plist-part n))
(define r-sieve (sieve (* 20 n)))
(define r-eval (eval-part n))
(report "deriv" r-deriv)
(report "sort" r-sort)
(report "closures" r-closure)
(report "plist" r-plist)
(report "sieve" r-sieve)
(report "eval" r-eval)
