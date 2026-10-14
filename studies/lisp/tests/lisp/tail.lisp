; Proper tail calls: loops written as recursion in every tail position the
; spec has: 100000 iterations through named let, cond, and/or, and mutual
; recursion between two global procedures; 10000 through if, or, begin,
; the bodies of let, let* and letrec, when, unless, case and a lambda's
; body.
; None of these fit in the machine's stack unless the calls are tail calls.
; (A cond clause with only a test is not a tail position: its value has to
; be checked.)

(define (show label x)
  (display label)
  (display ": ")
  (write x)
  (newline))

(define big 100000)
(define small 10000)

(show "named let" (let loop ((i 0)) (if (= i big) i (loop (+ i 1)))))

(define (count-if i) (if (< i small) (count-if (+ i 1)) i))
(show "if" (count-if 0))

(define (count-cond i)
  (cond ((= i big) i)
        ((< i 0) 'never)
        (t (count-cond (+ i 1)))))
(show "cond" (count-cond 0))

(define (count-and i) (and (< i (+ big 1)) (or (and (= i big) i) (count-and (+ i 1)))))
(show "and and or" (count-and 0))

(define (count-or i) (or (and (= i small) 'reached) (count-or (+ i 1))))
(show "or" (count-or 0))

(define (count-begin i) (begin 'ignored (if (= i small) i (count-begin (+ i 1)))))
(show "begin" (count-begin 0))

(define (count-let i) (let ((j (+ i 1))) (if (> j small) i (count-let j))))
(show "let body" (count-let 0))

(define (count-let* i) (let* ((j (+ i 1)) (k j)) (if (> k small) i (count-let* k))))
(show "let* body" (count-let* 0))

(define (count-letrec i) (letrec ((j (+ i 1))) (if (> j small) i (count-letrec j))))
(show "letrec body" (count-letrec 0))

(define (count-when i) (if (= i small) i (when t (count-when (+ i 1)))))
(show "when" (count-when 0))

(define (count-unless i) (if (= i small) i (unless nil (count-unless (+ i 1)))))
(show "unless" (count-unless 0))

(define (count-case i) (case (= i small) ((t) i) ((nil) (count-case (+ i 1)))))
(show "case" (count-case 0))

(define (count-lambda i) (if (= i small) i ((lambda (j) (count-lambda j)) (+ i 1))))
(show "a lambda's body" (count-lambda 0))

(define (my-even? n) (if (= n 0) t (my-odd? (- n 1))))
(define (my-odd? n) (if (= n 0) nil (my-even? (- n 1))))
(show "mutual recursion, even" (my-even? big))
(show "mutual recursion, odd" (my-odd? (+ small 1)))

(show "letrec mutual recursion"
      (letrec ((ping (lambda (n acc) (if (= n 0) acc (pong (- n 1) (+ acc 1)))))
               (pong (lambda (n acc) (if (= n 0) acc (ping (- n 1) (+ acc 2))))))
        (ping small 0)))

; (the closures are made by a separate procedure, so each one holds only
; its own n, not the loop's frame and through it every earlier closure)
(define (const-fn n) (lambda () n))
(define (loop-with-closure n f) (if (= n 0) (f) (loop-with-closure (- n 1) (const-fn n))))
(show "passing closures" (loop-with-closure small (const-fn 'start)))

(define (varargs-loop n . rest) (if (= n 0) rest (varargs-loop (- n 1) n)))
(show "a varargs procedure" (varargs-loop small))

(define (make-list n acc) (if (= n 0) acc (make-list (- n 1) (cons n acc))))
(define (sum-list l acc) (if (null? l) acc (sum-list (cdr l) (+ acc (car l)))))
(show "building and walking a list of 5000" (sum-list (make-list 5000 nil) 0))
