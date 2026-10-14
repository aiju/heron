; FIB: the Fibonacci numbers, two ways. The doubly recursive (fib n) is
; the classic benchmark of procedure calls and integer arithmetic (it is
; in Gabriel's set as FIB, and in most others); (fib 20) makes 21891 calls,
; 20 deep at most. The iterative version is a loop written as tail
; recursion with three variables, run to (fib 44), the largest that fits a
; fixnum.
;
; Exercises: calls and returns, if, <, +, -, named let.

(define (fib n)
  (if (< n 2)
      n
      (+ (fib (- n 1)) (fib (- n 2)))))

(define (fib-iter n)
  (if (= n 0)
      0
      (let loop ((i 1) (a 0) (b 1))    ; a = (fib (- i 1)), b = (fib i)
        (if (= i n)
            b
            (loop (+ i 1) b (+ a b))))))

(display "(fib 20) = ")
(write (fib 20))
(newline)

(display "(fib-iter 0..15) = ")
(write (let loop ((i 15) (acc nil))
         (if (< i 0) acc (loop (- i 1) (cons (fib-iter i) acc)))))
(newline)

(display "(fib-iter 44) = ")
(write (fib-iter 44))
(newline)

; the two agree
(display "agree for 0..20: ")
(write (let loop ((i 0))
         (cond ((> i 20) t)
               ((= (fib i) (fib-iter i)) (loop (+ i 1)))
               (t i))))
(newline)
