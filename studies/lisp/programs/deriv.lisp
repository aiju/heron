; DERIV: Gabriel's DERIV, symbolic differentiation of a polynomial with
; respect to x. Each derivative builds a fresh expression of about 60
; pairs that is thrown away at once, so this is mostly a test of cons and
; the garbage collector. Gabriel's version runs (deriv '(+ (* 3 x x) (* a x
; x) (* b x) 5)) 5000 times; this one runs it 2000 times.
;
; Exercises: cons, list, map with a global procedure, cond, eq?, quoted
; constants, garbage.

(define (deriv-aux a)
  (list '/ (deriv a) a))

(define (deriv a)
  (cond ((not (pair? a))
         (if (eq? a 'x) 1 0))
        ((eq? (car a) '+)
         (cons '+ (map deriv (cdr a))))
        ((eq? (car a) '-)
         (cons '- (map deriv (cdr a))))
        ((eq? (car a) '*)
         (list '* a (cons '+ (map deriv-aux (cdr a)))))
        ((eq? (car a) '/)
         (list '-
               (list '/ (deriv (cadr a)) (caddr a))
               (list '/ (cadr a) (list '* (caddr a) (caddr a) (deriv (caddr a))))))
        (t (error "no derivation method for" (car a)))))

(define expr '(+ (* 3 x x) (* a x x) (* b x) 5))

(define (count-pairs x)
  (if (pair? x)
      (+ 1 (count-pairs (car x)) (count-pairs (cdr x)))
      0))

(define (run n)
  (let loop ((i 0) (last nil))
    (if (= i n)
        last
        (loop (+ i 1) (deriv expr)))))

(define result (run 2000))
(display "d/dx ")
(write expr)
(newline)
(display "  = ")
(write result)
(newline)
(display "pairs in the result: ")
(write (count-pairs result))
(newline)
(display "a quotient: ")
(write (deriv '(/ (* x x) (+ x 1))))
(newline)
