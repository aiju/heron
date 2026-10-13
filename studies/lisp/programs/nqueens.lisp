; NQUEENS: count the ways to place n queens on an n-by-n board so that no
; two attack each other, the version in the Gambit and Larceny benchmark
; suites (by Marc Feeley), with lists for the rows still to place and the
; queens placed so far. (nqueens 8) is 92. Recursion stays under about 30
; levels.
;
; Exercises: list building with cons and append, recursion that isn't a
; tail call, and/not/=, small integers.

(define (one-to n)
  (let loop ((i n) (l nil))
    (if (= i 0) l (loop (- i 1) (cons i l)))))

(define (ok? row dist placed)
  (if (null? placed)
      t
      (and (not (= (car placed) (+ row dist)))
           (not (= (car placed) (- row dist)))
           (ok? row (+ dist 1) (cdr placed)))))

(define (try-it x y z)
  (if (null? x)
      (if (null? y) 1 0)
      (+ (if (ok? (car x) 1 z)
             (try-it (append (cdr x) y) nil (cons (car x) z))
             0)
         (try-it (cdr x) (cons (car x) y) z))))

(define (nqueens n)
  (try-it (one-to n) nil nil))

; one solution, for the record: the first one found, as columns by row
(define (first-solution n)
  (let try ((x (one-to n)) (y nil) (z nil))
    (cond ((null? x) (if (null? y) (reverse z) nil))
          ((and (ok? (car x) 1 z)
                (try (append (cdr x) y) nil (cons (car x) z))))
          (t (try (cdr x) (cons (car x) y) z)))))

(let loop ((n 1))
  (when (<= n 8)
    (display "(nqueens ")
    (write n)
    (display ") = ")
    (write (nqueens n))
    (newline)
    (loop (+ n 1))))

(display "first solution for 8: ")
(write (first-solution 8))
(newline)
