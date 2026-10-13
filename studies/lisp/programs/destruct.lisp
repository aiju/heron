; DESTRUCT: Gabriel's DESTRUCTIVE, list surgery with set-car! and
; set-cdr!: a list of 10 lists is repeatedly cut in half and spliced
; together, with new lists of nils appended when one runs empty. Gabriel's
; version is (destructive 600 50); this is (destructive 300 50). nconc
; isn't in the language, so it's defined here; Gabriel's prog1 becomes a
; let.
;
; Exercises: set-car!, set-cdr!, length, quotient, nested do loops,
; last-pair.

(define (nconc a b)
  (if (null? a)
      b
      (begin (set-cdr! (last-pair a) b) a)))

(define (destructive n m)
  (let ((l (do ((i 10 (- i 1))
                (a nil (cons nil a)))
               ((= i 0) a))))
    (do ((i n (- i 1)))
        ((= i 0))
      (cond ((null? (car l))
             (do ((l l (cdr l)))
                 ((null? l))
               (or (car l) (set-car! l (cons nil nil)))
               (nconc (car l)
                      (do ((j m (- j 1))
                           (a nil (cons nil a)))
                          ((= j 0) a)))))
            (t
             (do ((l1 l (cdr l1))
                  (l2 (cdr l) (cdr l2)))
                 ((null? l2))
               (set-cdr! (do ((j (quotient (length (car l2)) 2) (- j 1))
                              (a (car l2) (cdr a)))
                             ((zero? j) a)
                           (set-car! a i))
                         (let ((n (quotient (length (car l1)) 2)))
                           (cond ((= n 0)
                                  (set-car! l1 nil)
                                  (car l1))
                                 (t
                                  (do ((j n (- j 1))
                                       (a (car l1) (cdr a)))
                                      ((= j 1)
                                       (let ((r (cdr a)))
                                         (set-cdr! a nil)
                                         r))
                                    (set-car! a i))))))))))
    l))

(define result (destructive 300 50))
(display "lengths: ")
(write (map length result))
(newline)
(display "first list: ")
(write (car result))
(newline)
(define (sum-all l)
  (let loop ((l l) (s 0))
    (cond ((null? l) s)
          ((pair? (car l)) (loop (cdr l) (+ s (sum-all (car l)))))
          ((number? (car l)) (loop (cdr l) (+ s (car l))))
          (t (loop (cdr l) s)))))
(display "sum of the numbers: ")
(write (sum-all result))
(newline)
