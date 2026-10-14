; The prelude: the parts of the language the runtime defines in Lisp.
; It is read and evaluated at start-up, before the program.
;
; The macros use only %-names and the primitives' values captured here,
; so a program can define its own map, list?, append and the like.

(define %cons cons)
(define %append append)
(define %memq memq)

(define (%list? l)
  (cond ((null? l) t)
        ((pair? l) (%list? (cdr l)))
        (t nil)))
(define (%map f l)
  (if (null? l)
      nil
      (let ((x (f (car l))))
        (cons x (%map f (cdr l))))))
(define (%every f l)
  (cond ((null? l) t)
        ((f (car l)) (%every f (cdr l)))
        (t nil)))
(define (%bad form) (error "bad syntax" form))

; Quasiquote, one level deep.
(define (%qq x)
  (cond ((not (pair? x)) (list 'quote x))
        ((eq? (car x) 'unquote) (cadr x))
        ((and (pair? (car x)) (eq? (car (car x)) 'unquote-splicing))
         (list %append (cadr (car x)) (%qq (cdr x))))
        (t (list %cons (%qq (car x)) (%qq (cdr x))))))
(defmacro quasiquote (x) (%qq x))

(defmacro when (c . body) (list 'if c (cons 'begin body)))
(defmacro unless (c . body) (list 'if c nil (cons 'begin body)))

; (let name ((v init)...) body...), which the interpreter rewrites by this
(define (%named-let form)
  (let ((name (cadr form)) (bindings (caddr form)) (body (cdddr form)))
    (cons (list 'letrec
                (list (list name (cons 'lambda (cons (%map car bindings) body))))
                name)
          (%map cadr bindings))))

(define (%do-spec? s)
  (and (pair? s) (%list? s) (symbol? (car s)) (pair? (cdr s))
       (or (null? (cddr s)) (null? (cdddr s)))))

(defmacro do (specs test . body)
  (unless (and (%list? specs) (%every %do-spec? specs) (pair? test) (%list? test))
    (%bad (cons 'do (cons specs (cons test body)))))
  (let ((loop '%do-loop))           ; (not a gensym: programs count theirs from g1)
    (list 'let loop (%map (lambda (s) (list (car s) (cadr s))) specs)
          (list 'if (car test)
                (cons 'begin (cdr test))
                (cons 'begin
                      (%append body
                               (list (cons loop
                                           (%map (lambda (s)
                                                   (if (pair? (cddr s)) (caddr s) (car s)))
                                                 specs)))))))))

(defmacro case (key . clauses)
  (unless (%every (lambda (c) (and (pair? c) (%list? c) (or (eq? (car c) t) (%list? (car c)))))
                  clauses)
    (%bad (cons 'case (cons key clauses))))
  (let ((k '%case-key))
    (list 'let (list (list k key))
          (cons 'cond
                (%map (lambda (c)
                        (cons (if (eq? (car c) t) t (list %memq k (list 'quote (car c))))
                              (if (null? (cdr c)) '(nil) (cdr c))))
                      clauses)))))

(define (list-tail l k) (if (<= k 0) l (list-tail (cdr l) (- k 1))))
(define (list-ref l k) (car (list-tail l k)))
(define (last-pair l) (if (pair? (cdr l)) (last-pair (cdr l)) l))

(define (member x l)
  (let loop ((m l))
    (cond ((pair? m) (if (equal? x (car m)) m (loop (cdr m))))
          ((null? m) nil)
          (t (error "not a list" l)))))
(define (assoc x l)
  (let loop ((m l))
    (cond ((pair? m) (if (equal? x (car (car m))) (car m) (loop (cdr m))))
          ((null? m) nil)
          (t (error "not a list" l)))))

(define (map f l)
  (if (%list? l) (%map f l) (error "not a list" l)))
(define (for-each f l)
  (if (%list? l)
      (let loop ((l l))
        (if (null? l) nil (begin (f (car l)) (loop (cdr l)))))
      (error "not a list" l)))

(define (abs n) (if (< n 0) (- n) n))
(define (min a b) (if (< b a) b a))
(define (max a b) (if (< a b) b a))
(define (list? l) (%list? l))
