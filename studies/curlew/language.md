# The Curlew language

Curlew is a lazy, statically typed functional language. It reads like a
small Haskell 98, with Hindley–Milner type inference and single-parameter
type classes, and it borrows from Miranda where that keeps the language
small: a program is a function from its input to its output, and there is
one number type. This page says what's in it and where it differs from
Haskell; [implementation.md](implementation.md) says how it runs.

## A program

A program is one file of declarations: data types, type synonyms,
classes, instances, fixity declarations and functions. It must define

```haskell
main :: String -> String
```

The runtime applies `main` to the console input, as a lazy list of
characters, and prints the result as it's evaluated, so a program can be
interactive: the output that depends on the first line of input appears
before the second is read. There is no `IO` type and no other effect.
`main`'s type is given if the program doesn't give it.

```haskell
-- the lines of the input, numbered
main input = unlines (zipWith number [1..] (lines input))
  where number n l = show n ++ ": " ++ l
```

## Syntax

As Haskell's, with these parts:

- **Layout:** `where`, `let`, `do` and `of` open a block whose items line
  up; explicit `{ ; }` work too. A block also closes where the next token
  couldn't continue it (Haskell's parse-error rule), for the cases that
  come up: `in`, `then`, `else`, `of`, `where`, closing brackets, commas,
  `|`, `=` and `->`.
- **Comments:** `--` to the end of the line, and `{- -}`, nested.
- **Literals:** integers, characters and strings, with the escapes
  `\n \t \r \\ \' \" \0 \a \b \f \v`. A string is a list of characters.
- **Declarations:** functions by equations with patterns and guards,
  `where` on an equation, type signatures (several names may share one),
  `infixl`, `infixr` and `infix` for any operator, also a backquoted name
  or a constructor operator such as `:+`.
- **Expressions:** application, operators with their fixities, sections
  (`(+ 1)`, `(2 *)`, `(`div` 2)`), lambdas, `let`, `if`, `case`, guards in
  `case` alternatives, tuples, lists, ranges (`[a..]`, `[a, b..c]`),
  list comprehensions with generators, guards and `let`, `do` for any
  monad, and type annotations (`e :: t`).
- **Patterns:** variables, wildcards, literals (also strings), constructors,
  tuples, lists, `x@p`, lazy patterns `~p`, and bang patterns `!x` (the
  argument is evaluated before the body runs). `let !x = e in b` evaluates
  `e` first.

## Types

- **Built in:** `Int`, `Char`, functions, lists and tuples. The prelude
  defines `Bool`, `Ordering`, `Maybe`, `Either`, and the synonyms
  `String = [Char]` and `ShowS`.
- **`Int`** is 30 bits, signed: −2²⁹ to 2²⁹ − 1. An operation whose result
  doesn't fit is an error, not a wrap-around. Division by zero is an error
  too. `div` and `mod` round towards −∞, `quot` and `rem` towards zero.
- **`Char`** is a code; the input gives 0–255, and the output prints the
  low byte. `ord` and `chr` convert, without checks.
- **Data types** take type parameters, may be recursive, and may mark a
  field strict with `!`: the constructor evaluates it before building.
  `deriving` makes instances of `Eq`, `Ord`, `Show` and `Enum` (the last
  only for types whose constructors have no fields).
- **Type synonyms** with parameters, expanded where they're used.
- **Inference** is Hindley–Milner with let-polymorphism. A binding without
  arguments or a signature isn't generalised over class constraints (the
  monomorphism restriction), and a constraint left ambiguous defaults to
  `()`, or to `Int` where `()` has no instance, so that `show []` works.

There are no records, modules, `newtype`, type-class extensions, kinds
other than the ones inference finds, `Integer`, floating point or arrays.

## Classes

Single-parameter classes, with superclasses and default methods; the
parameter may be a type constructor, as in `Functor` and `Monad`. Instances
are for a type constructor applied to distinct type variables, with a
context: `instance Show a => Show (Maybe a)`, `instance Monad (State s)`.
A class's methods are passed as dictionaries, which the optimiser removes
where it can see the type (implementation.md).

The prelude's classes: `Eq`, `Ord` (superclass `Eq`), `Show` (with
`showsPrec` and `showList`, so strings show as strings), `Enum` (the
ranges), `Functor` and `Monad`. Arithmetic is not a class: the operators
are `Int`'s, and literals are `Int`s.

## The prelude

`prelude.cw` is compiled with every program, and only what a program uses
ends up in its code. It has Haskell 98's list functions (`map`, `filter`,
the folds and scans, `take`, `drop`, `splitAt`, `span`, `zip`, `zip3`,
`zipWith`, `lookup`, `elem`, `iterate`, `repeat`, `replicate`, `cycle`,
`reverse`, `concat`, `concatMap`, `and`, `or`, `any`, `all`, `sum`,
`product`, `maximum`, `minimum`, `lines`, `words` and their inverses,
`!!`), some of `Data.List` (`sort`, `sortBy`, `insert`, `nub`,
`partition`, `intercalate`, `transpose`, `foldl'`), the character tests
and conversions, `Maybe` and `Either` helpers, `fst`, `snd`, `curry`,
`uncurry`, `id`, `const`, `flip`, `.`, `$`, `$!`, `seq`, `until`,
`error`, `undefined`, `gcd`, `lcm`, `^`, bitwise operations on `Int`
(`andInt`, `orInt`, `xorInt`, `shiftL`, `shiftR`), `shows` and friends,
`mapM` and `sequence`, and `readInt`, which reads an optionally signed
decimal number.

## Errors

`error s`, a failed pattern match, an `Int` overflow, division by zero, a
stack or heap that runs out: each stops the program after the output so
far, with `error:` and a message on a line of its own. The prelude's partial
functions call `error` with their own messages (`head: empty list`).

## Where it differs from Haskell

- `main` is `String -> String`, as in Miranda and early Haskell; there is
  no `IO`.
- One number type, `Int`, of 30 bits, and overflow is an error.
- No `Num` class: `+` is `Int`'s, and a literal is an `Int`.
- No modules, records or `newtype`; `deriving` covers `Eq`, `Ord`,
  `Show` and `Enum`.
- Defaulting picks `()` first, which Haskell 98 doesn't have.
