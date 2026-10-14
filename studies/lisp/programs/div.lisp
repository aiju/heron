; DIV: Gabriel's DIV2, dividing by 2 the unary number represented by a
; list of 200 nils, iteratively (a do loop that conses the result) and
; recursively (cons on the way back from 100 nested calls). Gabriel's
; version does each 300 times, four times per iteration; this one does
; each 300 times.
;
; Exercises: cddr, cons, do loops, recursion that isn't a tail call, null?,
; garbage.

(define (create-n n)
  (do ((n n (- n 1))
       (a nil (cons nil a)))
      ((= n 0) a)))

(define ll (create-n 200))

(define (iterative-div2 l)
  (do ((l l (cddr l))
       (a nil (cons (car l) a)))
      ((null? l) a)))

(define (recursive-div2 l)
  (cond ((null? l) nil)
        (t (cons (car l) (recursive-div2 (cddr l))))))

(define (test-1 l)
  (do ((i 300 (- i 1))
       (r nil (iterative-div2 l)))
      ((= i 0) r)))

(define (test-2 l)
  (do ((i 300 (- i 1))
       (r nil (recursive-div2 l)))
      ((= i 0) r)))

(display "(length ll) = ")
(write (length ll))
(newline)
(display "iterative: ")
(write (length (test-1 ll)))
(newline)
(display "recursive: ")
(write (length (test-2 ll)))
(newline)
(display "of 10: ")
(write (list (iterative-div2 (create-n 10)) (recursive-div2 (create-n 10))))
(newline)
