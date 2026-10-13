; SORT: sorting 1000 pseudo-random integers three ways: merge sort and
; quicksort on lists, and an in-place quicksort on a vector. The numbers
; come from a linear congruential generator, x' = (1021 x + 12345) mod
; 2^20, whose intermediate values stay below 2^30 (1021 * (2^20 - 1) +
; 12345 < 2^30), so it never overflows a fixnum. Each sort runs 3 times on
; fresh copies; the program prints a checksum of the sorted result and
; whether it is in order.
;
; Exercises: comparisons, list building and walking, iterative merging
; (no recursion as deep as the list), recursion about 2 log n deep,
; vector-ref and vector-set!, logand, modulo.

(define seed 42)
(define (random-next)
  (set! seed (logand (+ (* 1021 seed) 12345) 1048575))
  seed)

(define (random-list n)
  (let loop ((i 0) (acc nil))
    (if (= i n) acc (loop (+ i 1) (cons (random-next) acc)))))

; ---- merge sort on lists
(define (split l)
  ; two halves: every other element
  (let loop ((l l) (a nil) (b nil))
    (if (null? l)
        (cons a b)
        (loop (cdr l) (cons (car l) b) a))))

(define (merge a b)
  ; iterative: collect the smaller heads in reverse, then reverse
  (let loop ((a a) (b b) (acc nil))
    (cond ((null? a) (append (reverse acc) b))
          ((null? b) (append (reverse acc) a))
          ((< (car b) (car a)) (loop a (cdr b) (cons (car b) acc)))
          (t (loop (cdr a) b (cons (car a) acc))))))

(define (merge-sort l)
  (if (or (null? l) (null? (cdr l)))
      l
      (let ((halves (split l)))
        (merge (merge-sort (car halves)) (merge-sort (cdr halves))))))

; ---- quicksort on lists
(define (partition pivot l)
  (let loop ((l l) (less nil) (more nil))
    (cond ((null? l) (cons less more))
          ((< (car l) pivot) (loop (cdr l) (cons (car l) less) more))
          (t (loop (cdr l) less (cons (car l) more))))))

(define (quicksort l)
  (if (null? l)
      nil
      (let ((parts (partition (car l) (cdr l))))
        (append (quicksort (car parts))
                (cons (car l) (quicksort (cdr parts)))))))

; ---- quicksort in a vector
(define (list->vector l)
  (let ((v (make-vector (length l) 0)))
    (let loop ((l l) (i 0))
      (if (null? l) v (begin (vector-set! v i (car l)) (loop (cdr l) (+ i 1)))))))

(define (vector->list v)
  (let loop ((i (- (vector-length v) 1)) (acc nil))
    (if (< i 0) acc (loop (- i 1) (cons (vector-ref v i) acc)))))

(define (swap! v i j)
  (let ((t1 (vector-ref v i)))
    (vector-set! v i (vector-ref v j))
    (vector-set! v j t1)))

(define (vsort! v lo hi)
  ; sorts v[lo..hi] (inclusive); the middle element is the pivot
  (when (< lo hi)
    (swap! v lo (quotient (+ lo hi) 2))
    (let ((pivot (vector-ref v lo)))
      (let loop ((i (+ lo 1)) (last lo))
        (cond ((<= i hi)
               (if (< (vector-ref v i) pivot)
                   (begin (swap! v (+ last 1) i) (loop (+ i 1) (+ last 1)))
                   (loop (+ i 1) last)))
              (t
               (swap! v lo last)
               (vsort! v lo (- last 1))
               (vsort! v (+ last 1) hi)))))))

(define (vector-sort l)
  (let ((v (list->vector l)))
    (vsort! v 0 (- (vector-length v) 1))
    (vector->list v)))

; ---- checking
(define (sorted? l)
  (or (null? l)
      (null? (cdr l))
      (and (<= (car l) (cadr l)) (sorted? (cdr l)))))

(define (checksum l)
  (let loop ((l l) (acc 0))
    (if (null? l) acc (loop (cdr l) (modulo (+ (* acc 31) (car l)) 1000003)))))

(define (copy l) (append l nil))

(define (take l n)
  (if (= n 0) nil (cons (car l) (take (cdr l) (- n 1)))))

(define data (random-list 1000))
(display "first ten: ")
(write (take data 10))
(newline)

(define (bench name sort)
  (let loop ((i 0) (r nil))
    (if (< i 3)
        (loop (+ i 1) (sort (copy data)))
        (begin
          (display name)
          (display ": checksum ")
          (write (checksum r))
          (display ", sorted ")
          (write (sorted? r))
          (display ", length ")
          (write (length r))
          (display ", least ")
          (write (car r))
          (display ", greatest ")
          (write (car (last-pair r)))
          (newline)
          r))))

(define r1 (bench "merge sort" merge-sort))
(define r2 (bench "quicksort" quicksort))
(define r3 (bench "vector quicksort" vector-sort))
(display "all the same: ")
(write (and (equal? r1 r2) (equal? r2 r3)))
(newline)
(display "the input is unchanged: ")
(write (= (length data) 1000))
(newline)
