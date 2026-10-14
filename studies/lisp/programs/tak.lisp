; TAK: Gabriel's TAK, the Takeuchi function (Ikuo Takeuchi), the classic
; test of procedure calls: (tak 18 12 6) makes 63609 calls and returns 7,
; with recursion at most a few dozen deep. Then a smaller run of Gabriel's
; TAKL, the same function on lists, where the numbers are list lengths
; and "less than" compares lists by walking them.
;
; Exercises: calls with 3 arguments, deeply nested non-tail calls, <, -;
; TAKL: car/cdr, null?, list walking.

(define (tak x y z)
  (if (not (< y x))
      z
      (tak (tak (- x 1) y z)
           (tak (- y 1) z x)
           (tak (- z 1) x y))))

(display "(tak 18 12 6) = ")
(write (tak 18 12 6))
(newline)

; TAKL
(define (listn n)
  (if (= n 0)
      nil
      (cons n (listn (- n 1)))))

(define (shorterp x y)
  (and (not (null? y))
       (or (null? x)
           (shorterp (cdr x) (cdr y)))))

(define (mas x y z)
  (if (not (shorterp y x))
      z
      (mas (mas (cdr x) y z)
           (mas (cdr y) z x)
           (mas (cdr z) x y))))

(display "(takl 12 8 4) = ")
(write (mas (listn 12) (listn 8) (listn 4)))
(newline)
