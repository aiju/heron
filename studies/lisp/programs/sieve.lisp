; SIEVE: the sieve of Eratosthenes in a vector of 10000 flags, the
; classic array benchmark (as in the Byte sieve, and Gabriel's style of
; tight integer loops). It runs 3 times, then prints how many primes there
; are below 10000, the last few, and their sum.
;
; Exercises: make-vector, vector-ref, vector-set!, do loops, integer
; arithmetic, building a list of the results.

(define size 10000)

(define (sieve n)
  ; a vector of n flags, t where the index is prime
  (let ((flags (make-vector n t)))
    (vector-set! flags 0 nil)
    (vector-set! flags 1 nil)
    (do ((i 2 (+ i 1)))
        ((> (* i i) n) flags)
      (when (vector-ref flags i)
        (do ((j (* i i) (+ j i)))
            ((>= j n))
          (vector-set! flags j nil))))))

(define (primes flags)
  ; the indexes that are flagged, as a list in increasing order
  (do ((i (- (vector-length flags) 1) (- i 1))
       (acc nil (if (vector-ref flags i) (cons i acc) acc)))
      ((< i 0) acc)))

(define (count-primes flags)
  (do ((i 0 (+ i 1))
       (n 0 (if (vector-ref flags i) (+ n 1) n)))
      ((= i (vector-length flags)) n)))

(define flags
  (do ((k 0 (+ k 1))
       (f nil (sieve size)))
      ((= k 3) f)))

(define (take l n)
  (if (= n 0) nil (cons (car l) (take (cdr l) (- n 1)))))

(define ps (primes flags))
(display "primes below ")
(write size)
(display ": ")
(write (count-primes flags))
(newline)
(display "the first ten: ")
(write (take ps 10))
(newline)
(display "the last five: ")
(write (list-tail ps (- (length ps) 5)))
(newline)
(display "their sum: ")
(write (apply + ps))
(newline)
