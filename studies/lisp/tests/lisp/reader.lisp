; The reader and the printer: integer and symbol tokens, nil and (), the
; quote and quasiquote abbreviations, comments, dotted pairs, strings and
; their escapes, what ends a token; write and display of every kind of
; value; (read) taking data from the input after the form being
; evaluated; and, at the very end, the end-of-file object.

(define (show label x)
  (display label)
  (display ": ")
  (write x)
  (newline))

(define (note s) (display s) (newline))

; ---- tokens
(show "integers" '(0 1 -1 +1 42 -42 007 -0))
(show "integer?" (map integer? '(12 +12 -12 1+ 1a +a - + 1-2 --1)))
(show "symbols" '(+ - 1+ -1a a1 +- 1-2 --1 ...))
(show "punctuation in symbols" '(set-car! <= a->b *x* %y $z & ^ ~ ! ? @ #foo a.b .. .5 \x |y|))
(show "case-sensitive" (list (eq? 'abc 'ABC) (eq? 'abc 'abc) 'MiXeD))
(show "nil reads as nil" (list (eq? 'nil '()) (symbol? 'nil) (null? 'nil)))
(show "() reads as nil" '(() (()) (nil) ( )))
(show "t is a symbol" (list (symbol? 't) (eq? t 't)))
(show "high bytes" '(café naïve))

; ---- quote abbreviations
(show "quote" ''x)
(show "quasiquote" '`x)
(show "unquote" '(a ,b))
(show "unquote-splicing" '(a ,@b))
(show "all of them" '`(a ,b ,@c 'd))
(show "quote of a list" ''(1 2))
(show "nested quotes" '''a)
(show "space after a quote" ' x)
(show "comma, space, @" '(, @x))
(show "car of a quote form" (car ''a))

; ---- comments
(show "comments" '(1 ; a comment
                   2 ;; another
                   ; a whole line
                   3))
(show "a comment ends a token" '(a;comment
b))
; a comment between forms (with a "string" and a ) in it)
(show "after a comment" 'ok)

; ---- dotted pairs
(show "dotted pair" '(1 . 2))
(show "dotted list" '(1 2 . 3))
(show "dot then a list" '(1 . (2 3)))
(show "dot then nil" '(1 . nil))
(show "dot then ()" '(1 . ()))
(show "dot then a quote" '(1 . 'x))
(show "dot then a string" '(1 . "s"))
(show "dot before a parenthesis" '(1 .(2)))
(show "a symbol starting with a dot" '(a .b))
(show "nested dotted" '((1 . 2) (3 . 4) . 5))
(show "dotted with spaces" '( 1  .  2 ))

; ---- strings
(show "escapes" "a\"b\\c\nd")
(display "displayed: a\"b\\c\nd")
(newline)
(show "length with escapes" (string-length "a\"b\\c\nd"))
(show "codes of escapes" (list (string-ref "\n" 0) (string-ref "\\" 0) (string-ref "\"" 0)))
(show "another escaped character is itself" "\q\t")
(show "empty string" "")
(show "a newline in a string" "line1
line2")
(show "a string with ; and parentheses" "a ; b ( c ) 'd")
(show "high bytes in a string" "café")
(show "a tab is printed as it is" "a	b")

; ---- what ends a token
(show "a string" '(a"s"b))
(show "a quote" '(a'b))
(show "parentheses" '(a(b)c))
(show "a comma" '(a,b))
(show "a backquote" '(a`b))
(show "newlines and tabs" '(a
	b))

; ---- the printer
(show "nested lists" '(1 (2 (3 (4))) ((5))))
(show "a quote form" '(quote x))
(show "quote forms inside" '(a 'b `c ,d))
(show "negative integers" '(-1 -1073741824))
(define v (make-vector 3 0))
(vector-set! v 0 "s")
(vector-set! v 1 '(1 . "2"))
(vector-set! v 2 (make-vector 1 'in))
(show "a vector" v)
(show "an empty vector" (make-vector 0 0))
(show "a list holding a vector" (list 1 v))
(show "procedures" (list car (lambda () 1)))
(display "display: ")
(display (list "a" '("b" . "c") v 'sym 12 "q\"uote"))
(newline)
(display "display a string with a newline: ")
(display "x\ny")
(newline)
(display "write: ")
(write (list "a" '("b" . "c") 'sym 12))
(newline)
(display "write-char: ")
(write-char 72)
(write-char 105)
(write-char 33)
(write-char 10)

; ---- (read): the data after the form being evaluated
(show "read a symbol" (read)) hello
(show "read a list" (read)) (1 (2 "three") . four)
(show "read a quote" (read)) 'x
(show "read a string" (read)) "s\"t"
(show "read an integer" (read)) -123
(show "read nil" (read)) ()
(show "read two" (list (read) (read))) first second
(define (read-until stop)
  (let ((x (read)))
    (if (eq? x stop) nil (cons x (read-until stop)))))
(show "read until end" (read-until 'end)) 1 2 (3 4) "five" end
(show "read past a comment" (read)) ; a comment
  (x ; inside
   y)
(show "read evaluates nothing" (read)) (car 5)
(show "eval what was read" (eval (read))) (+ 1 2)
(note "read of a stray )")
(show "never" (read)) )
(note "read of a literal out of range")
(show "never" (read)) 1073741824
(note "carrying on")

(show "done" 'reader)
(let ((e (read)))
  (show "the end of the input" e)
  (show "eof-object?" (eof-object? e))
  (show "read again" (eof-object? (read))))
; a comment after the last form
