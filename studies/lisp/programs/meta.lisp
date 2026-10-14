; META: a small Lisp interpreter written in Lisp, the classic metacircular
; evaluator: eval and apply over S-expressions, environments as lists of
; association lists, closures as tagged lists, primitives borrowed from
; the host. It runs a recursive fib, a list reversal and a higher-order
; program, so the host runs an interpreter interpreting a program.
;
; Exercises: symbolic dispatch with cond and eq?, assq lookups, deep
; recursion through eval and apply, apply with host primitives, closures
; represented as data.

(define (m-lookup var env)
  (if (null? env)
      (error "m-eval: unbound" var)
      (let ((b (assq var (car env))))
        (if b (cdr b) (m-lookup var (cdr env))))))

(define (m-define! var val env)
  (let ((b (assq var (car env))))
    (if b
        (set-cdr! b val)
        (set-car! env (cons (cons var val) (car env))))))

(define (m-set! var val env)
  (if (null? env)
      (error "m-eval: unbound" var)
      (let ((b (assq var (car env))))
        (if b (set-cdr! b val) (m-set! var val (cdr env))))))

(define (m-bind params args env)
  (let loop ((p params) (a args) (frame nil))
    (cond ((null? p) (cons frame env))
          ((symbol? p) (cons (cons (cons p a) frame) env))
          (t (loop (cdr p) (cdr a) (cons (cons (car p) (car a)) frame))))))

(define (m-eval x env)
  (cond ((symbol? x) (m-lookup x env))
        ((not (pair? x)) x)
        ((eq? (car x) 'quote) (cadr x))
        ((eq? (car x) 'if)
         (if (m-eval (cadr x) env)
             (m-eval (caddr x) env)
             (if (pair? (cdddr x)) (m-eval (cadddr x) env) nil)))
        ((eq? (car x) 'lambda) (list 'closure (cadr x) (cddr x) env))
        ((eq? (car x) 'define)
         (if (pair? (cadr x))
             (m-define! (car (cadr x))
                        (list 'closure (cdr (cadr x)) (cddr x) env)
                        env)
             (m-define! (cadr x) (m-eval (caddr x) env) env))
         (if (pair? (cadr x)) (car (cadr x)) (cadr x)))
        ((eq? (car x) 'set!) (m-set! (cadr x) (m-eval (caddr x) env) env))
        ((eq? (car x) 'begin) (m-eval-body (cdr x) env))
        ((eq? (car x) 'let)
         (m-eval-body (cddr x)
                      (m-bind (map car (cadr x))
                              (m-eval-list (map cadr (cadr x)) env)
                              env)))
        ((eq? (car x) 'cond) (m-eval-cond (cdr x) env))
        (t (m-apply (m-eval (car x) env) (m-eval-list (cdr x) env)))))

(define (m-eval-list l env)
  (if (null? l)
      nil
      (let ((v (m-eval (car l) env)))
        (cons v (m-eval-list (cdr l) env)))))

(define (m-eval-body body env)
  (if (null? (cdr body))
      (m-eval (car body) env)
      (begin (m-eval (car body) env) (m-eval-body (cdr body) env))))

(define (m-eval-cond clauses env)
  (cond ((null? clauses) nil)
        ((m-eval (car (car clauses)) env) (m-eval-body (cdr (car clauses)) env))
        (t (m-eval-cond (cdr clauses) env))))

(define (m-apply f args)
  (if (and (pair? f) (eq? (car f) 'closure))
      (m-eval-body (caddr f) (m-bind (cadr f) args (cadddr f)))
      (apply f args)))

(define global-env
  (list (list (cons 'car car) (cons 'cdr cdr) (cons 'cons cons)
              (cons 'null? null?) (cons 'pair? pair?) (cons 'eq? eq?)
              (cons '+ +) (cons '- -) (cons '* *) (cons '< <) (cons '= =)
              (cons 'list list) (cons 't t))))

(define (run program)
  (let loop ((forms program) (v nil))
    (if (null? forms)
        v
        (loop (cdr forms) (m-eval (car forms) global-env)))))

(define fib-program
  '((define (fib n) (if (< n 2) n (+ (fib (- n 1)) (fib (- n 2)))))
    (fib 15)))

(define reverse-program
  '((define (rev l acc) (if (null? l) acc (rev (cdr l) (cons (car l) acc))))
    (define (iota n) (let ((l nil)) (define (loop i) (if (= i 0) l (begin (set! l (cons i l)) (loop (- i 1))))) (loop n)))
    (rev (iota 30) nil)))

(define higher-order-program
  '((define (map f l) (if (null? l) nil (cons (f (car l)) (map f (cdr l)))))
    (define (compose f g) (lambda (x) (f (g x))))
    (define (adder n) (lambda (x) (+ x n)))
    (define (counter)
      (let ((n 0)) (lambda () (set! n (+ n 1)) n)))
    (define c (counter))
    (c) (c)
    (list (map (compose (adder 10) (lambda (x) (* x x))) '(1 2 3 4 5))
          (c)
          (cond ((eq? 'a 'b) 'no) ((pair? '(1)) 'yes) (t 'never)))))

(display "fib 15: ")
(write (run fib-program))
(newline)
(display "reverse: ")
(write (run reverse-program))
(newline)
(display "higher order: ")
(write (run higher-order-program))
(newline)
