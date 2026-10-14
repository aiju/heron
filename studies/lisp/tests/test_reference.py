"""The reference interpreter: it must reproduce every expected output
(programs/expected/ and tests/lisp/expected/, which it wrote with
--write-expected), so they can't drift from it unnoticed; and a few of the
spec's finer points, checked directly."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))

try:
    from heron.studies.lisp import reference
except ImportError:  # run directly, without the heron package
    sys.path.insert(0, os.path.dirname(HERE))
    import reference


def run(text):
    return reference.run(text.encode() if isinstance(text, str) else text)


class Expected(unittest.TestCase):
    """Each program and feature test prints exactly its expected output."""

    def check(self, path, exp):
        name = os.path.relpath(path, os.path.dirname(HERE))
        self.assertTrue(os.path.exists(exp), f"{name}: no expected output (reference.py --write-expected)")
        with open(path, "rb") as f:
            text = f.read()
        with open(exp, "rb") as f:
            expected = f.read()
        out = reference.run(text)
        if out != expected:
            k = next((i for i, (a, b) in enumerate(zip(out, expected)) if a != b), min(len(out), len(expected)))
            self.fail(f"{name}: output differs at byte {k}:\n"
                      f"  got      {out[max(0, k - 60):k + 60]!r}\n"
                      f"  expected {expected[max(0, k - 60):k + 60]!r}")

    def test_every_program_has_a_test(self):
        self.assertGreater(len(reference.programs()), 0)


def _make(path, exp):
    return lambda self: self.check(path, exp)


for _p, _e in reference.programs():
    _dir = os.path.basename(os.path.dirname(_p))
    _name = os.path.basename(_p)[:-5].replace("-", "_")
    setattr(Expected, f"test_{_dir}_{_name}", _make(_p, _e))


class Fixnums(unittest.TestCase):
    def test_range(self):
        self.assertEqual(run("(write (list 1073741823 -1073741824))"), b"(1073741823 -1073741824)")

    def test_overflow(self):
        for expr in ["(+ 1073741823 1)", "(- -1073741824 1)", "(- -1073741824)",
                     "(* 32768 32768)", "(* -1073741824 -1)", "(quotient -1073741824 -1)",
                     "(abs -1073741824)", "(ash 1 30)", "(ash 3 29)", "(ash 1 1000000)",
                     "1073741824", "-1073741825", "123456789012345678901234567890"]:
            with self.subTest(expr):
                self.assertEqual(run(expr + " (write 'next)"), b"error: overflow\nnext")

    def test_overflow_is_checked_at_each_step(self):
        self.assertEqual(run("(+ 1073741823 1 -1)"), b"error: overflow\n")
        self.assertEqual(run("(write (+ 1073741823 -1 1))"), b"1073741823")

    def test_edges_in_range(self):
        cases = {"(ash -1 30)": b"-1073741824", "(* 32768 -32768)": b"-1073741824",
                 "(- 1073741823)": b"-1073741823", "(remainder -1073741824 -1)": b"0",
                 "(modulo -1073741824 -1)": b"0", "(ash -1073741824 -100)": b"-1",
                 "(ash 1073741823 -100)": b"0", "(ash 0 1000000)": b"0",
                 "(logxor -1073741824 -1)": b"1073741823", "(logand -8 -3)": b"-8",
                 "(logior -1073741824 1073741823)": b"-1"}
        for expr, want in cases.items():
            with self.subTest(expr):
                self.assertEqual(run(f"(write {expr})"), want)

    def test_division_signs(self):
        self.assertEqual(run("(write (list (quotient -7 2) (remainder -7 2) (modulo -7 2) (modulo 7 -2)))"),
                         b"(-3 -1 1 -1)")


class Printer(unittest.TestCase):
    def test_string_escapes(self):
        self.assertEqual(run(r'(write "a\"b\\c' + "\n" + r'd\ne")'), rb'"a\"b\\c\nd\ne"')
        self.assertEqual(run(r'(display "a\"b\\c\nd")'), b'a"b\\c\nd')

    def test_other_bytes_are_raw(self):
        self.assertEqual(run('(write "\tx\x01\xff")'.encode("latin-1")), b'"\tx\x01\xff"')

    def test_quote_forms_print_as_lists(self):
        self.assertEqual(run("(write '('a `b ,c ,@d))"),
                         b"((quote a) (quasiquote b) (unquote c) (unquote-splicing d))")

    def test_lists(self):
        self.assertEqual(run("(write '(1 (2 . 3) (4 5 . 6) () . 7))"), b"(1 (2 . 3) (4 5 . 6) nil . 7)")

    def test_display_is_recursive(self):
        self.assertEqual(run('(display \'("a" ("b" . "c")))'), b"(a (b . c))")
        self.assertEqual(run('(let ((v (make-vector 2 "s"))) (display v) (write v))'), b'#(s s)#("s" "s")')

    def test_other_objects(self):
        self.assertEqual(run("(write (list car (lambda () 1) (make-vector 0 0) (read)))"),
                         b"(#<procedure> #<procedure> #() #<eof>)")


class Errors(unittest.TestCase):
    def test_format(self):
        self.assertEqual(run("(car 5)"), b"error: not a pair: 5\n")
        self.assertEqual(run("(car)"), b"error: wrong number of arguments\n")
        self.assertEqual(run('(error "my message" \'(1 2) \'foo "s")'), b'error: my message: (1 2) foo "s"\n')
        self.assertEqual(run('(error "alone")'), b"error: alone\n")

    def test_program_continues(self):
        self.assertEqual(run("(write 1) (car 5) (write 2)"), b"1error: not a pair: 5\n2")

    def test_first_argument_checked(self):
        self.assertEqual(run("(+ 1 'a 'b)"), b"error: not a number: a\n")
        self.assertEqual(run("(vector-ref 5 'x)"), b"error: not a vector: 5\n")

    def test_call_order(self):
        # operator and operands are evaluated before the operator is checked
        self.assertEqual(run("((begin (write 1) 5) (write 2))"), b"12error: not a procedure: 5\n")
        # and the arity is checked when the procedure is applied
        self.assertEqual(run("((lambda (x) x) (write 1) (write 2))"), b"12error: wrong number of arguments\n")

    def test_end_of_input_ends_the_program(self):
        self.assertEqual(run('(write 1) (write "abc'), b"1error: unexpected end of input\n")
        self.assertEqual(run("(write (read)) (1 2"), b"error: unexpected end of input\n")
        self.assertEqual(run("(write 1) ' "), b"1error: unexpected end of input\n")

    def test_unexpected_close(self):
        self.assertEqual(run(") (write 1)"), b"error: unexpected )\n1")

    def test_bad_syntax(self):
        self.assertEqual(run("(if)"), b"error: bad syntax: (if)\n")
        self.assertEqual(run("(lambda (1) 1)"), b"error: bad syntax: (lambda (1) 1)\n")


class Evaluation(unittest.TestCase):
    def test_read_takes_what_follows_the_form(self):
        self.assertEqual(run("(write (read)) foo (write (list (read) (read))) (a) \"b\""), b'foo((a) "b")')
        self.assertEqual(run("(write (eof-object? (read)))  ; nothing after"), b"t")

    def test_tail_calls_run_in_constant_stack(self):
        # with a small recursion limit, only proper tail calls get through
        old = sys.getrecursionlimit()
        sys.setrecursionlimit(400)
        try:
            out = reference._run(b"""
                (define (ev? n) (if (= n 0) t (od? (- n 1))))
                (define (od? n) (cond ((= n 0) nil) (t (ev? (- n 1)))))
                (write (ev? 20000))
                (write (let loop ((i 0)) (and (<= i 20000) (or (and (= i 20000) 'x) (loop (+ i 1))))))
                (write (do ((i 0 (+ i 1))) ((= i 20000) i)))
                (define (via-apply n) (if (= n 0) 'done (apply via-apply (list (- n 1)))))
                (write (via-apply 20000))""")
        finally:
            sys.setrecursionlimit(old)
        self.assertEqual(out, b"tx20000done")

    def test_gensym_counts_from_1_in_each_run(self):
        self.assertEqual(run("(write (list (gensym) (gensym)))"), b"(g1 g2)")
        self.assertEqual(run("(write (gensym))"), b"g1")

    def test_state_does_not_leak_between_runs(self):
        run("(define leaked 1) (put 'p 'k 1) (defmacro if (a) a)")
        self.assertEqual(run("(write (get 'p 'k)) (write (if t 1 2)) leaked"),
                         b"nil1error: unbound variable: leaked\n")

    def test_define_sets_the_global(self):
        self.assertEqual(run("(define (f) (define g 1) 2) (write (list (f) g))"), b"(2 1)")

    def test_macro_expansion(self):
        self.assertEqual(run("(defmacro m (a . r) `(list ',a ,@r)) (write (m x 1 (+ 1 1)))"), b"(x 1 2)")
        self.assertEqual(run("(defmacro m (a) a) (m)"), b"error: wrong number of arguments\n")

    def test_equal(self):
        self.assertEqual(run("(write (list (equal? '(1 (\"a\")) '(1 (\"a\"))) (eq? \"a\" \"a\") (eq? 5 5)))"),
                         b"(t nil t)")


if __name__ == "__main__":
    unittest.main()
