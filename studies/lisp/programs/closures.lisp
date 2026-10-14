; CLOSURES: higher-order programming, in the style of the closure-heavy
; Scheme benchmarks (map/fold pipelines, composed and curried procedures,
; counters, memoization, Church numerals). Not one classic program but a
; mix of the idioms they test, each run enough times to matter.
;
; Exercises: making closures, calling procedures passed as values,
; varargs and apply, set! on captured variables, closures capturing loop
; variables, map and for-each with lambdas, assq tables, vectors of
; procedures.

(define (iota n)
  ; (0 1 ... n-1)
  (let loop ((i (- n 1)) (acc nil))
    (if (< i 0) acc (loop (- i 1) (cons i acc)))))

(define (fold-left f acc l)
  (if (null? l) acc (fold-left f (f acc (car l)) (cdr l))))

(define (fold-right f init l)
  ; recursive: as deep as the list is long (200 here)
  (if (null? l) init (f (car l) (fold-right f init (cdr l)))))

(define (filter keep? l)
  (let loop ((l l) (acc nil))
    (cond ((null? l) (reverse acc))
          ((keep? (car l)) (loop (cdr l) (cons (car l) acc)))
          (t (loop (cdr l) acc)))))

(define (compose . fs)
  (if (null? fs)
      (lambda (x) x)
      (let ((f (car fs))
            (g (apply compose (cdr fs))))
        (lambda (x) (f (g x))))))

(define (curry f) (lambda (a) (lambda (b) (f a b))))
(define (make-adder n) (lambda (x) (+ x n)))

(define numbers (iota 200))

; ---- map, filter and fold, 30 times over 200 numbers
(define (pipeline l)
  (fold-left + 0
             (map (lambda (x) (* x x))
                  (filter (lambda (x) (= (remainder x 3) 0)) l))))
(display "sum of squares of multiples of 3 below 200: ")
(write (let loop ((i 0) (r 0)) (if (= i 30) r (loop (+ i 1) (pipeline numbers)))))
(newline)
(display "fold-right cons copies: ")
(write (equal? (fold-right cons nil numbers) numbers))
(newline)
(display "fold-left builds in reverse: ")
(write (fold-left (lambda (acc x) (cons x acc)) nil (iota 10)))
(newline)

; ---- composition and currying
(define add10 (apply compose (map make-adder (iota 5))))
(define times2 ((curry *) 2))
(define f (compose times2 add10 times2))
(display "composed (2 * (x * 2 + 10)) over 0..9: ")
(write (map f (iota 10)))
(newline)
(display "composed over 200, 20 times: ")
(write (let loop ((i 0) (r 0))
         (if (= i 20) r (loop (+ i 1) (fold-left + 0 (map f numbers))))))
(newline)
(define adders (map (curry +) (iota 10)))
(display "curried adders applied to 100: ")
(write (map (lambda (g) (g 100)) adders))
(newline)

; ---- counters: closures with their own state
(define (make-counter)
  (let ((n 0))
    (lambda msg
      (cond ((null? msg) (set! n (+ n 1)) n)
            ((eq? (car msg) 'get) n)
            ((eq? (car msg) 'reset) (set! n 0) 'reset)
            (t (error "unknown message" (car msg)))))))
(define counters (make-vector 10 nil))
(do ((i 0 (+ i 1))) ((= i 10)) (vector-set! counters i (make-counter)))
(define seed 7)
(define (random-index)
  (set! seed (modulo (+ (* seed 75) 74) 65537))
  (remainder seed 10))
(do ((i 0 (+ i 1))) ((= i 3000)) ((vector-ref counters (random-index))))
(display "counts: ")
(write (map (lambda (i) ((vector-ref counters i) 'get)) (iota 10)))
(newline)
(display "total: ")
(write (fold-left + 0 (map (lambda (i) ((vector-ref counters i) 'get)) (iota 10))))
(newline)
((vector-ref counters 0) 'reset)
(display "after a reset: ")
(write ((vector-ref counters 0) 'get))
(newline)

; ---- closures capturing loop variables
(define thunks
  (do ((i 0 (+ i 1))
       (acc nil (cons (lambda () (* i i)) acc)))
      ((= i 100) acc)))
(display "100 thunks from a do loop, summed: ")
(write (fold-left + 0 (map (lambda (th) (th)) thunks)))
(newline)
(define named-thunks
  (let loop ((i 0) (acc nil))
    (if (= i 5) (reverse acc) (loop (+ i 1) (cons (lambda () i) acc)))))
(display "from a named let: ")
(write (map (lambda (th) (th)) named-thunks))
(newline)

; ---- two closures sharing one variable
(define (make-account balance)
  (list (lambda (amount) (set! balance (+ balance amount)) balance)
        (lambda (amount)
          (if (> amount balance)
              'insufficient
              (begin (set! balance (- balance amount)) balance)))
        (lambda () balance)))
(define acct (make-account 100))
(define deposit (car acct))
(define withdraw (cadr acct))
(define balance (caddr acct))
(display "account: ")
(write (list (deposit 50) (withdraw 30) (withdraw 500) (balance)))
(newline)

; ---- memoization in a closure, with an assq table
(define (memoize f)
  (let ((table nil))
    (lambda (n)
      (let ((hit (assq n table)))
        (if hit
            (cdr hit)
            (let ((v (f n)))
              (set! table (cons (cons n v) table))
              v))))))
(define memo-fib
  (memoize (lambda (n)
             (if (< n 2) n (+ (memo-fib (- n 1)) (memo-fib (- n 2)))))))
(display "memoized (fib 40): ")
(write (memo-fib 40))
(newline)

; ---- Church numerals
(define church-zero (lambda (f) (lambda (x) x)))
(define (church-succ n) (lambda (f) (lambda (x) (f ((n f) x)))))
(define (church-add m n) (lambda (f) (lambda (x) ((m f) ((n f) x)))))
(define (church-mul m n) (lambda (f) (m (n f))))
(define (church->int n) ((n (lambda (k) (+ k 1))) 0))
(define (int->church k) (if (= k 0) church-zero (church-succ (int->church (- k 1)))))
(define c3 (int->church 3))
(define c4 (int->church 4))
(display "Church numerals 3+4, 3*4, (3*4)*(3+4): ")
(write (list (church->int (church-add c3 c4))
             (church->int (church-mul c3 c4))
             (church->int (church-mul (church-mul c3 c4) (church-add c3 c4)))))
(newline)
