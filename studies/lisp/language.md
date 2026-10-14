# The language

A small, lexically scoped Lisp with one namespace (a Lisp-1, like
Scheme), in which `nil` is the empty list and also false (as in older
Lisps). It's meant to be enough for the benchmark programs and for a
compiler written in itself, not a standard. The runtime on the machine
([implementation.md](implementation.md)) and the reference interpreter
(`reference.py`) implement exactly this, and print exactly the same
output for every program, error messages included.

## Data

| Type | Written as | Notes |
|---|---|---|
| Integer | `42`, `-7` | 31-bit signed, −2³⁰ to 2³⁰ − 1 (fixnums). Arithmetic that leaves the range is an `overflow` error. No bignums, no floats. |
| Symbol | `foo`, `set-car!`, `1+`, `<=` | Case-sensitive. Interned, except those `gensym` makes. |
| `nil` | `nil`, `()` | The empty list, and false. Not a symbol: `(symbol? nil)` is `nil`. |
| `t` | `t` | A symbol whose value is itself; what predicates return for true. Everything but `nil` is true. |
| Pair | `(a . b)`, `(1 2 3)` | |
| String | `"text"` | Escapes `\"`, `\\` and `\n`. Immutable. |
| Vector | (no syntax) | Made with `make-vector`; prints as `#(1 2 3)`. |
| Procedure | | Primitives, interpreted closures, compiled closures. All print as `#<procedure>`. |
| End of file | | What `read` returns at the end of input; test it with `eof-object?`. Prints as `#<eof>`. |

The reader:

- A token is an integer if it matches `[+-]?[0-9]+`, and a symbol
  otherwise. Tokens end at whitespace, `(`, `)`, `'`, `` ` ``, `,`, `"`
  and `;`. An integer literal outside the fixnum range is an `overflow`
  error.
- `nil` reads as `nil`, not as a symbol.
- `'x` is `(quote x)`, `` `x `` is `(quasiquote x)`, `,x` is
  `(unquote x)` and `,@x` is `(unquote-splicing x)`.
- `;` starts a comment to the end of the line.
- A `.` between whitespace in a list makes a dotted pair.

The printer (`write`; `display` is the same but prints strings without
quotes or escapes):

- integers in decimal, symbols by name, `nil`, `t`;
- lists as `(1 2 3)` and `(1 . 2)`, with `quote` forms printed as lists:
  `'x` prints as `(quote x)`;
- strings as `"a\"b"` (escaping `"`, `\` and newline as `\n`);
- vectors as `#(1 2 3)`, procedures as `#<procedure>`, the end-of-file
  object as `#<eof>`.

## Evaluation

Integers, strings, `nil`, `t`, vectors and procedures evaluate to
themselves. A symbol evaluates to its value in the innermost lexical scope
that binds it, else its global value; an unbound one is an error.

A pair is a special form if its car is one of the special-form symbols
below or a macro's name; otherwise it's a call: the operator and the
arguments are evaluated left to right, and the operator's value is applied
to the arguments. Special-form and macro names are reserved: binding them
as variables is not supported.

Calls in tail position are proper tail calls, in the interpreter and in
compiled code, so loops written as recursion run in constant stack space.

### Special forms

| Form | Meaning |
|---|---|
| `(quote x)` | `x`, unevaluated |
| `(if c a)`, `(if c a b)` | `a` if `c` isn't `nil`, else `b` (or `nil`) |
| `(define name expr)` | Set the *global* value of `name`, wherever the `define` is. Returns `name`. |
| `(define (name . params) body...)` | `(define name (lambda params body...))` |
| `(set! name expr)` | Assign the innermost binding of `name`, or its global value. Returns the value. |
| `(lambda params body...)` | A closure. `params` is `(a b)`, `(a b . rest)` or `rest`. |
| `(begin e...)` | Evaluate in order; the value of the last, or `nil` |
| `(let ((v init)...) body...)` | Inits evaluated in the outer scope |
| `(let name ((v init)...) body...)` | Named let: `((letrec ((name (lambda (v...) body...))) name) init...)` |
| `(let* ((v init)...) body...)` | Each init sees the bindings before it |
| `(letrec ((v init)...) body...)` | The variables are bound (to `nil`) first, then the inits are evaluated in the new scope and assigned in order |
| `(cond (test e...)... )` | The first clause whose test isn't `nil`: its last `e`, or the test's value if it has no `e`. A test of `t` (the symbol) is just true. No clause: `nil`. `else` is not special; write `t`. |
| `(and e...)` | `nil` at the first `nil`, else the last value; `(and)` is `t` |
| `(or e...)` | The first value that isn't `nil`, else `nil` |
| `(defmacro name params body...)` | Define a macro: a call `(name args...)` is replaced by the result of applying `(lambda params body...)` to the *unevaluated* args, and that is evaluated instead. Returns `name`. |

A body (`body...`) is evaluated like `begin`. There are no internal
definitions: `define` always sets a global.

### Macros in the prelude

The prelude, written in the language itself and loaded at start-up,
defines:

| Form | Meaning |
|---|---|
| `` `x ``, `,x`, `,@x` | Quasiquote, one level deep (no nested quasiquotes) |
| `(when c body...)`, `(unless c body...)` | |
| `(do ((v init step)...) (test res...) body...)` | Scheme's `do`; a variable without `step` keeps its value |
| `(case key ((d...) e...)... (t e...))` | Compares with `eq?`; `t` as the last clause's data is the default |

## Procedures

Unless a procedure says otherwise, giving it a value of the wrong type is
an error (see [Errors](#errors)).

**Pairs and lists**

| Procedure | |
|---|---|
| `(cons a b)`, `(car p)`, `(cdr p)` | |
| `(set-car! p x)`, `(set-cdr! p x)` | Return `x` |
| `caar cadr cdar cddr caddr cdddr cadddr` | Compositions of `car` and `cdr` |
| `(list x...)` | |
| `(length l)` | A proper list's length |
| `(append l...)` | Copies all but the last list |
| `(reverse l)` | |
| `(list-tail l k)`, `(list-ref l k)`, `(last-pair l)` | |
| `(memq x l)`, `(assq x al)` | Compare with `eq?` |
| `(member x l)`, `(assoc x al)` | Compare with `equal?` |
| `(map f l)`, `(for-each f l)` | One list only |

**Predicates and equality.** These return `t` or `nil`.

| Procedure | |
|---|---|
| `(eq? a b)` | Same object; integers are `eq?` when equal |
| `(equal? a b)` | `eq?`, or pairs with `equal?` cars and cdrs, or strings with the same characters |
| `(not x)`, `(null? x)` | `x` is `nil` |
| `pair? atom? symbol? number? integer? string? vector? procedure? list?` | `atom?` is "not a pair"; `list?` is "a proper list" |
| `(eof-object? x)` | |

**Arithmetic.** Integers only; every result must fit 31 bits.

| Procedure | |
|---|---|
| `(+ n...)`, `(* n...)` | `(+)` is 0, `(*)` is 1 |
| `(- n m...)` | `(- n)` is −n |
| `(quotient n m)` | Rounds toward zero |
| `(remainder n m)` | The sign of `n` |
| `(modulo n m)` | The sign of `m` |
| `(= a b)`, `(< a b)`, `(> a b)`, `(<= a b)`, `(>= a b)` | Exactly two arguments |
| `(zero? n)` | |
| `(abs n)`, `(min a b)`, `(max a b)` | Exactly one or two arguments |
| `(logand a b)`, `(logior a b)`, `(logxor a b)` | Bitwise, on the 31-bit two's complement values |
| `(ash n k)` | `n` shifted left by `k` (right, arithmetically, if `k` < 0) |

**Symbols and strings**

| Procedure | |
|---|---|
| `(gensym)` | A new uninterned symbol, `g1`, `g2`, ... in order |
| `(symbol->string s)`, `(string->symbol s)` | |
| `(string-length s)`, `(string-ref s k)` | `string-ref` gives the character's code |
| `(string=? a b)` | |
| `(get sym key)`, `(put sym key value)` | The symbol's property list, compared with `eq?`; `get` returns `nil` if there is none; `put` returns `value` |

**Vectors**

| Procedure | |
|---|---|
| `(make-vector n fill)` | |
| `(vector-ref v k)`, `(vector-set! v k x)`, `(vector-length v)` | `vector-set!` returns `x` |

**Control and the system**

| Procedure | |
|---|---|
| `(apply f l)` | Call `f` with the elements of `l` as arguments |
| `(eval x)` | Evaluate `x` in the global scope |
| `(error msg x...)` | Signal an error: `msg` is a string, the `x` are irritants |
| `(read)` | The next datum of the console input, or the end-of-file object |
| `(write x)`, `(display x)`, `(newline)` | Return `nil` |
| `(write-char n)` | Write the byte `n`; returns `nil` |
| `(gc)` | Collect garbage now; returns `nil` |

The runtime on the machine has more procedures for itself and the compiler
(their names start with `%`); [implementation.md](implementation.md) lists
them.

## Programs and the top level

A program is the console input: a sequence of forms, read and evaluated
one at a time until the end of the input. Their values aren't printed;
programs print with `display` and `write`. `(read)` inside a program reads
the next datum from the same input, after the form being evaluated.

## Errors

An error prints a line and abandons the top-level form being evaluated;
the program carries on with the next form. The line is `error: ` and the
message, then, if there are irritants, `: ` and the irritants written
(`write`) and separated by spaces:

```
error: not a pair: 5
error: wrong number of arguments
error: my message: (1 2) foo
```

| Message | Irritant | When |
|---|---|---|
| `not a pair` | the value | `car`, `cdr`, `set-car!`, `set-cdr!` and their compositions |
| `not a list` | the list | `length`, `reverse`, `append`, `apply`, `map`, `for-each` and the like on an improper list |
| `not a number` | the value | arithmetic, comparisons, `zero?`, `ash`, `log...` |
| `not a procedure` | the value | applying something else |
| `not a symbol`, `not a string`, `not a vector` | the value | |
| `unbound variable` | the symbol | |
| `wrong number of arguments` | – | |
| `division by zero` | – | `quotient`, `remainder`, `modulo` |
| `overflow` | – | a result or a literal outside the fixnum range |
| `index out of range` | the index | `vector-ref`, `vector-set!`, `string-ref`, `make-vector` with a negative size |
| `bad syntax` | the form | a malformed special form |
| `unexpected )` | – | the reader, at the top level |
| `unexpected end of input` | – | the reader, inside a datum; the program then ends |
| *the message* | the irritants | `(error "message" x...)` |

Where an error has several causes, the first argument checked is the one
reported: for `(+ 1 'a)` that's `a`, for `(vector-ref 5 'x)` it's `5`.
