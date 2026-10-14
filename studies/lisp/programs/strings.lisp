; STRINGS: symbol and string work: building symbols from strings and
; strings from symbols, character codes with string-ref, a word index in an
; association list, gensym for fresh names, and printing with write and
; display. The language's strings are immutable and can't be built
; character by character, so the text comes from symbols' names.
;
; Exercises: symbol->string, string->symbol, string-length, string-ref,
; string=?, equal? on strings, assq and assoc tables, gensym, property
; lists, write and display of strings with escapes.

(define words
  '(the quick brown fox jumps over the lazy dog and the dog sleeps while
    the fox runs over the hill and the quick dog follows the brown fox))

; ---- a word count in an association list (assq on symbols)
(define (count-words l)
  (let loop ((l l) (table nil))
    (if (null? l)
        table
        (let ((entry (assq (car l) table)))
          (if entry
              (begin (set-cdr! entry (+ (cdr entry) 1)) (loop (cdr l) table))
              (loop (cdr l) (cons (cons (car l) 1) table)))))))

; ---- the same with the names as strings (assoc on strings)
(define (count-names l)
  (let loop ((l l) (table nil))
    (if (null? l)
        table
        (let* ((name (symbol->string (car l)))
               (entry (assoc name table)))
          (if entry
              (begin (set-cdr! entry (+ (cdr entry) 1)) (loop (cdr l) table))
              (loop (cdr l) (cons (cons name 1) table)))))))

; ---- characters
(define (string-sum s)
  (let loop ((i 0) (sum 0))
    (if (= i (string-length s)) sum (loop (+ i 1) (+ sum (string-ref s i))))))

(define (vowels s)
  (let loop ((i 0) (n 0))
    (if (= i (string-length s))
        n
        (loop (+ i 1)
              (if (memq (string-ref s i) '(97 101 105 111 117)) (+ n 1) n)))))

(define (longest l)
  (let loop ((l l) (best ""))
    (cond ((null? l) best)
          ((> (string-length (symbol->string (car l))) (string-length best))
           (loop (cdr l) (symbol->string (car l))))
          (t (loop (cdr l) best)))))

; ---- symbols back from strings: interned, so eq?
(define (round-trip l)
  (let loop ((l l) (ok t))
    (if (null? l)
        ok
        (loop (cdr l) (and ok (eq? (string->symbol (symbol->string (car l))) (car l)))))))

; ---- gensym and property lists: tag each distinct word with a fresh name
(define (tag-words l)
  (for-each (lambda (w) (if (not (get w 'tag)) (put w 'tag (gensym)))) l)
  (map (lambda (w) (get w 'tag)) l))

(define (repeat n thunk)
  (let loop ((i 1) (v (thunk)))
    (if (= i n) v (loop (+ i 1) (thunk)))))

(display "word counts: ")
(write (repeat 30 (lambda () (count-words words))))
(newline)
(display "name counts: ")
(write (repeat 30 (lambda () (count-names words))))
(newline)
(display "character sums: ")
(write (repeat 30 (lambda () (map (lambda (w) (string-sum (symbol->string w))) words))))
(newline)
(display "vowels: ")
(write (repeat 30 (lambda () (map (lambda (w) (vowels (symbol->string w))) words))))
(newline)
(display "longest: ")
(write (longest words))
(display " ")
(display (longest words))
(newline)
(display "round trip: ")
(write (repeat 30 (lambda () (round-trip words))))
(newline)
(display "tags: ")
(write (tag-words words))
(newline)
(display "strings: ")
(write (list "plain" "with \"quotes\"" "back\\slash" "new\nline"))
(newline)
(display (list "plain" "with \"quotes\"" "back\\slash"))
(newline)
(display "equal strings: ")
(write (list (equal? "abc" "abc") (string=? "abc" "abd") (eq? 'abc (string->symbol "abc"))))
(newline)
